"""
PitBoss — KI-Kontingent-Tracking  (additiv, 0.4.7.1)
==================================================================

Zweck
-----
Die Gemini-API hat KEINEN Endpoint fuer "verbleibendes Kontingent". Google
erzwingt die Limits serverseitig und antwortet bei Ueberschreitung mit HTTP 429.
Eine Uebersicht muss die App daher LOKAL fuehren:

  * Requests pro Tag   -> das bindende Tageslimit ist RPD (Reset Mitternacht PT).
  * Tokens pro Tag     -> aus usageMetadata.totalTokenCount jeder Antwort.
  * Warnschwellen      -> 80 % / 90 % / 95 % des konfigurierten Tagesbudgets.
  * 429                -> harter Live-Indikator, getrennt gemeldet.

Persistenz: exports/ai_quota_usage.json  (kein Key, keine Prompts — nur Zaehler).

Einbindung (minimal)
--------------------
    from ai_quota import QuotaTracker, QuotaPanel

    self.quota = QuotaTracker()                      # einmal in __init__
    panel = QuotaPanel(self.quota)                   # irgendwo ins UI / "Mehr"-Menue

    # nach JEDEM Gemini-Call, direkt wo du die Antwort schon geparst hast:
    self.quota.record(
        usage_metadata=data.get("usageMetadata"),    # dict oder None
        http_status=status_code,                     # int, z.B. 200 / 429
        error_body=raw_body_bei_fehler,              # optional: str fuer 429-Klassifikation
    )

    # optional auf Warnungen reagieren (Statusleiste, TTS spaeter, ...):
    self.quota.threshold_reached.connect(lambda pct, used, budget:
        self.statusBar().showMessage(f"KI-Kontingent: {pct} % ({used}/{budget})", 8000))
    self.quota.rate_limited.connect(lambda kind, msg:
        self.statusBar().showMessage(f"Gemini-Limit erreicht ({kind}): {msg}", 12000))
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")   # Google-RPD-Reset liegt auf Mitternacht PT
except Exception:                            # tzdata evtl. nicht vorhanden -> lokale Zeit
    _PT = None

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QSpinBox, QFormLayout
)

# --- Theme: Orange-Akzent (an dein 0.4.6.0-Theme angleichen) ---------------
ACCENT   = "#FF5A00"
OK_COLOR = "#3FB950"
WARN_80  = "#E3B341"
WARN_90  = "#F0883E"
WARN_95  = "#F85149"

DEFAULT_STORE = os.path.join("exports", "ai_quota_usage.json")


def _today_key() -> str:
    """Datumsschluessel in Pacific Time, damit der Reset zu Googles RPD passt."""
    now = datetime.now(_PT) if _PT else datetime.now()
    return now.strftime("%Y-%m-%d")


def _reset_hint() -> str:
    return "Reset taeglich um Mitternacht Pacific Time (Google-RPD)."


@dataclass
class QuotaConfig:
    request_budget: int = 1500       # RPD-Default Flash-Free-Tier (konfigurierbar!)
    token_budget: int = 0            # 0 = nur informativ, keine Warnung auf Tokens
    warn_thresholds: tuple = (80, 90, 95)


class QuotaTracker(QObject):
    """Zaehlt Requests/Tokens pro (PT-)Tag und meldet Schwellen + 429."""

    usage_changed   = Signal(int, int, int, int)   # req_used, req_budget, tok_used, tok_budget
    threshold_reached = Signal(int, int, int)       # pct(80/90/95), req_used, req_budget
    rate_limited      = Signal(str, str)            # kind("RPD"/"RPM-TPM"/"429"), message

    def __init__(self, store_path: str = DEFAULT_STORE, config: QuotaConfig | None = None):
        super().__init__()
        self.cfg = config or QuotaConfig()
        self.store_path = store_path
        self._day = _today_key()
        self._requests = 0
        self._tokens = 0
        self._fired: set[int] = set()   # bereits gemeldete Schwellen am aktuellen Tag
        self._load()

    # -- Persistenz -----------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.store_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            if blob.get("day") == self._day:
                self._requests = int(blob.get("requests", 0))
                self._tokens = int(blob.get("tokens", 0))
                self._fired = set(int(x) for x in blob.get("fired", []))
            saved_cfg = blob.get("config")
            if isinstance(saved_cfg, dict):
                self.cfg.request_budget = int(saved_cfg.get("request_budget", self.cfg.request_budget))
                self.cfg.token_budget = int(saved_cfg.get("token_budget", self.cfg.token_budget))
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        blob = {
            "day": self._day,
            "requests": self._requests,
            "tokens": self._tokens,
            "fired": sorted(self._fired),
            "config": {"request_budget": self.cfg.request_budget,
                       "token_budget": self.cfg.token_budget},
        }
        tmp = self.store_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, indent=2)
        os.replace(tmp, self.store_path)   # atomar, keine halbe Datei bei Absturz

    def _roll_day_if_needed(self) -> None:
        key = _today_key()
        if key != self._day:
            self._day, self._requests, self._tokens, self._fired = key, 0, 0, set()

    # -- Kern: nach jedem Gemini-Call aufrufen --------------------------------
    def record(self, usage_metadata: dict | None = None,
               http_status: int | None = None, error_body: str | None = None) -> None:
        self._roll_day_if_needed()

        if http_status == 429:
            kind = "429"
            body = (error_body or "").lower()
            if "per day" in body or "rpd" in body or "quota exceeded" in body:
                kind = "RPD"       # erst nach Reset (Mitternacht PT) wieder frei
            elif "per minute" in body or "rpm" in body or "tpm" in body:
                kind = "RPM-TPM"   # kurzer Backoff (10-60 s) reicht
            self.rate_limited.emit(kind, error_body or "Gemini hat mit HTTP 429 geantwortet.")
            # 429 zaehlt nicht als erfolgreicher Request
            self._emit_usage()
            return

        # erfolgreicher Call
        self._requests += 1
        if usage_metadata:
            tok = usage_metadata.get("totalTokenCount")
            if tok is None:  # Fallback: Summe der Teilzaehler
                tok = (usage_metadata.get("promptTokenCount", 0)
                       + usage_metadata.get("candidatesTokenCount", 0)
                       + usage_metadata.get("thoughtsTokenCount", 0))
            self._tokens += int(tok or 0)

        self._check_thresholds()
        self._save()
        self._emit_usage()

    def _check_thresholds(self) -> None:
        if self.cfg.request_budget <= 0:
            return
        pct = int(self._requests * 100 / self.cfg.request_budget)
        for t in self.cfg.warn_thresholds:
            if pct >= t and t not in self._fired:
                self._fired.add(t)
                self.threshold_reached.emit(t, self._requests, self.cfg.request_budget)

    def _emit_usage(self) -> None:
        self.usage_changed.emit(self._requests, self.cfg.request_budget,
                                self._tokens, self.cfg.token_budget)

    # -- Setter fuers UI ------------------------------------------------------
    def set_request_budget(self, value: int) -> None:
        self.cfg.request_budget = max(1, int(value))
        self._fired.clear()          # Schwellen bei neuem Budget neu bewerten
        self._check_thresholds()
        self._save()
        self._emit_usage()

    def set_token_budget(self, value: int) -> None:
        self.cfg.token_budget = max(0, int(value))
        self._save()
        self._emit_usage()

    @property
    def snapshot(self) -> dict:
        return {"day": self._day, "requests": self._requests, "tokens": self._tokens,
                "request_budget": self.cfg.request_budget, "token_budget": self.cfg.token_budget}


class QuotaPanel(QWidget):
    """Kompakte Anzeige: Requests-Gauge (mit Schwellenfarbe), Tokens, Budget-Setter."""

    def __init__(self, tracker: QuotaTracker, parent=None):
        super().__init__(parent)
        self.tracker = tracker
        self.setObjectName("QuotaPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        title = QLabel("KI-Kontingent (Gemini)")
        title.setStyleSheet(f"font-weight:600; color:{ACCENT};")
        root.addWidget(title)

        # Requests
        self.req_label = QLabel()
        self.req_bar = QProgressBar()
        self.req_bar.setTextVisible(True)
        root.addWidget(self.req_label)
        root.addWidget(self.req_bar)

        # Tokens
        self.tok_label = QLabel()
        self.tok_bar = QProgressBar()
        self.tok_bar.setTextVisible(True)
        root.addWidget(self.tok_label)
        root.addWidget(self.tok_bar)

        # Budget-Setter
        form = QFormLayout()
        self.req_spin = QSpinBox()
        self.req_spin.setRange(1, 1_000_000)
        self.req_spin.setValue(tracker.cfg.request_budget)
        self.req_spin.setSuffix(" Req/Tag")
        self.req_spin.valueChanged.connect(tracker.set_request_budget)
        form.addRow("Tagesbudget:", self.req_spin)

        self.tok_spin = QSpinBox()
        self.tok_spin.setRange(0, 100_000_000)
        self.tok_spin.setSingleStep(10_000)
        self.tok_spin.setValue(tracker.cfg.token_budget)
        self.tok_spin.setSpecialValueText("aus (nur Info)")
        self.tok_spin.setSuffix(" Tok/Tag")
        self.tok_spin.valueChanged.connect(tracker.set_token_budget)
        form.addRow("Token-Budget:", self.tok_spin)
        root.addLayout(form)

        hint = QLabel(_reset_hint() + "\nGemini liefert kein Rest-Kontingent — lokal gezaehlt; 429 = hartes Limit.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8b949e; font-size:11px;")
        root.addWidget(hint)

        tracker.usage_changed.connect(self._on_usage)
        tracker.rate_limited.connect(self._on_rate_limited)
        self._rl_note = QLabel("")
        self._rl_note.setWordWrap(True)
        root.addWidget(self._rl_note)

        self._on_usage(*_as_tuple(tracker.snapshot))

    def _on_usage(self, req_used, req_budget, tok_used, tok_budget):
        pct = int(req_used * 100 / req_budget) if req_budget else 0
        self.req_label.setText(f"Requests heute: {req_used} / {req_budget}  ({pct} %)")
        self.req_bar.setMaximum(req_budget)
        self.req_bar.setValue(min(req_used, req_budget))
        self.req_bar.setStyleSheet(_bar_qss(_color_for_pct(pct)))

        if tok_budget > 0:
            tpct = int(tok_used * 100 / tok_budget)
            self.tok_label.setText(f"Tokens heute: {tok_used} / {tok_budget}  ({tpct} %)")
            self.tok_bar.setMaximum(tok_budget)
            self.tok_bar.setValue(min(tok_used, tok_budget))
            self.tok_bar.setStyleSheet(_bar_qss(_color_for_pct(tpct)))
        else:
            self.tok_label.setText(f"Tokens heute: {tok_used}  (Budget aus)")
            self.tok_bar.setMaximum(1)
            self.tok_bar.setValue(0)
            self.tok_bar.setStyleSheet(_bar_qss("#30363d"))

    def _on_rate_limited(self, kind, msg):
        color = WARN_95 if kind in ("RPD", "429") else WARN_90
        tip = "Reset erst Mitternacht PT." if kind == "RPD" else "Kurzer Backoff (10-60 s) reicht."
        self._rl_note.setText(f"Limit erreicht ({kind}) — {tip}")
        self._rl_note.setStyleSheet(f"color:{color}; font-weight:600;")


def _color_for_pct(pct: int) -> str:
    if pct >= 95:
        return WARN_95
    if pct >= 90:
        return WARN_90
    if pct >= 80:
        return WARN_80
    return OK_COLOR


def _bar_qss(color: str) -> str:
    return (f"QProgressBar{{border:1px solid #30363d;border-radius:4px;"
            f"background:#0d1117;text-align:center;color:#e6edf3;height:16px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:3px;}}")


def _as_tuple(snap: dict):
    return (snap["requests"], snap["request_budget"], snap["tokens"], snap["token_budget"])


# --- Eigenstaendiger Demo-Modus: python ai_quota.py ---------------------------
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QPushButton

    app = QApplication(sys.argv)
    trk = QuotaTracker(store_path=os.path.join("exports", "ai_quota_demo.json"),
                       config=QuotaConfig(request_budget=20, token_budget=50000))
    win = QWidget()
    win.setStyleSheet("background:#161b22;color:#e6edf3;")
    lay = QVBoxLayout(win)
    lay.addWidget(QuotaPanel(trk))

    btn = QPushButton("Fake-Call (+1 Request, ~1200 Tokens)")
    btn.clicked.connect(lambda: trk.record(usage_metadata={"totalTokenCount": 1200}, http_status=200))
    lay.addWidget(btn)

    btn429 = QPushButton("Fake 429 (RPD)")
    btn429.clicked.connect(lambda: trk.record(http_status=429, error_body="Quota exceeded: requests per day"))
    lay.addWidget(btn429)

    trk.threshold_reached.connect(lambda p, u, b: print(f"[WARN] {p}% erreicht: {u}/{b}"))
    win.resize(360, 320)
    win.show()
    sys.exit(app.exec())
