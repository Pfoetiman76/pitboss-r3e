import csv
import json
import os
# Suppress harmless Qt warnings as early as possible, before PySide6 loads.
os.environ.setdefault("QT_LOGGING_RULES", "*.warning=false")
import math
import sys
import subprocess
import shutil
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, astuple as _dc_astuple, fields as _dc_fields
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt, QPointF, QRectF, QUrl, qInstallMessageHandler, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QAbstractItemView,  # 0.2.14: EditTrigger-Enum fuer den Sitzungs-Browser
    QApplication, QFileDialog, QGroupBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTableWidget, QComboBox,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QTabWidget, QFrame,
    QCheckBox, QSpinBox, QProgressDialog, QSizeGrip, QDialog, QDialogButtonBox, QScrollArea, QSlider
)

import ctypes
from tts import SpeechEngine  # 0.4.7.2: Offline-Sprachausgabe
import updater  # 0.4.7.5: Update-Pruefung ueber GitHub Releases
import ai_providers  # 0.2.1: optionale KI-Anbieter fuer den Live-Coach
from raceroom_sm import R3EReader  # RaceRoom Shared Memory ($R3E)
import vr_overlay  # 0.4.0.0: VR-Tafel (PBVR-Shared-Memory, siehe vr_overlay.py)
from corner_db import CORNER_SECTIONS  # 0.2.38: echte Kurvennamen (Basis: SealHUD, MIT)
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QIcon, QPixmap, QDesktopServices, QShortcut, QKeySequence, QFont, QFontMetricsF, QPainterPath, QImage

APP_VERSION = "0.4.0.4 Beta"
AUTO_SWITCH_DEBOUNCE_SAMPLES = 20  # 0.5.9.24: ~2s bei 10 Hz, bevor ein Strecken-/Fahrzeugwechsel als real gilt
APP_DIR = Path(__file__).resolve().parent

def _default_data_dir():
    """Nutzerdaten (Fahrer-Profil, Reports, Configs, Logs) unter
    Dokumente\\PitBoss R3E statt neben der EXE. Fallback: Home bzw. exports/."""
    try:
        home = Path.home()
        docs = home / "Documents"
        return (docs if docs.is_dir() else home) / "PitBoss R3E"
    except Exception:
        return APP_DIR / "exports"

EXPORT_DIR = _default_data_dir()
REPORT_DIR = EXPORT_DIR / "reports"
CSV_DIR = EXPORT_DIR / "csv"
REFERENCE_DIR = EXPORT_DIR / "references"
DRIVER_PROFILE_PATH = EXPORT_DIR / "driver_hardware_profiles.json"
DRIVER_PROFILE_STATE_PATH = EXPORT_DIR / "driver_hardware_profile_state.json"
PROFILE_ASSET_DIR = EXPORT_DIR / "profile_assets"
LOG_DIR = EXPORT_DIR / "logs"  # 0.4.8.8: automatische Log-Dateien
BRAKE_MODEL_PATH = EXPORT_DIR / "brake_model.json"  # 0.4.9.2
DAMAGE_MODEL_PATH = EXPORT_DIR / "damage_model.json"  # 0.4.9.4
COACH_TIMING_PATH = EXPORT_DIR / "coach_timing.json"  # 0.4.9.8: Ansage-Vorlauf
OVERLAY_SIZES_PATH = EXPORT_DIR / "overlay_sizes.json"  # 0.4.9.8: Overlay-Groessen
BLINDSPOT_CONFIG_PATH = EXPORT_DIR / "blindspot.json"  # 0.5.9.13: Toter-Winkel (Flip)
VR_CONFIG_PATH = EXPORT_DIR / "vr_overlay.json"  # 0.4.0.0: VR-Overlay (aktiv + Leinwand-Rahmen)
HOTKEY_CONFIG_PATH = EXPORT_DIR / "hotkeys.json"  # 0.2.5: frei belegbare Hotkeys (Stream Deck)
UI_LAYOUT_PATH = EXPORT_DIR / "ui_layout.json"  # 0.2.10: Einfache Ansicht vs. Experte
ANALYSIS_CONFIG_PATH = EXPORT_DIR / "analysis_config.json"  # 0.2.31: Auswertungs-Optionen
FEEDBACK_DIR = EXPORT_DIR / "feedback"  # 0.2.33: Beta-Tester-Feedback (offline gespeicherte Dateien)
FUEL_HISTORY_PATH = EXPORT_DIR / "fuel_history.json"  # 0.3.1.3: Verbrauch pro Strecke/Auto fuer den Sprit-Rechner


def load_fuel_history() -> dict:
    """0.3.1.3: {\"Strecke|Auto\": {\"fuel_l\": [...], \"lap_s\": [...], ...}} laden."""
    try:
        raw = json.loads(FUEL_HISTORY_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_fuel_history(data: dict) -> bool:
    """0.3.1.3: Verbrauchs-Historie in Dokumente\\\\PitBoss R3E\\\\fuel_history.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        FUEL_HISTORY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

def load_analysis_config() -> dict:
    """0.2.31: {"include_invalid_laps": bool} laden; ungueltig -> Standard."""
    try:
        raw = json.loads(ANALYSIS_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {"include_invalid_laps": False}

def save_analysis_config(cfg: dict) -> bool:
    """0.2.31: Auswertungs-Optionen in Dokumente\\PitBoss R3E\\analysis_config.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        ANALYSIS_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

# 0.2.10: Einfache Ansicht - nur diese Hauptansichten, der Rest bleibt
# ueber den Experte-Modus (Mehr > Einfache Ansicht) erreichbar. Nichts wird geloescht.
SIMPLE_VIEWS = ("Dashboard", "Live", "Coach")

def load_ui_layout() -> bool:
    """0.2.10: True = Einfache Ansicht (Standard), False = Experte mit allen Ansichten."""
    try:
        raw = json.loads(UI_LAYOUT_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return bool(raw.get("simple", True))
    except Exception:
        pass
    return True

def save_ui_layout(simple: bool) -> bool:
    """0.2.10: Ansichts-Modus in Dokumente\\PitBoss R3E\\ui_layout.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        UI_LAYOUT_PATH.write_text(json.dumps({"simple": bool(simple)}, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

# 0.2.13: Sitzungs-Index - Metadaten (Strecke/Fahrzeug/Runden/Bestzeit) und
# eigene Namen fuer gespeicherte Reports. Die Report-Dateien bleiben unangetastet.
SESSIONS_INDEX_PATH = EXPORT_DIR / "sessions.json"

def load_sessions_index() -> dict:
    """0.2.13: {"names": {...}, "meta": {...}} laden; ungueltig -> leere Struktur."""
    try:
        raw = json.loads(SESSIONS_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {"names": {}, "meta": {}}

def save_sessions_index(idx: dict) -> bool:
    """0.2.13: Sitzungs-Index in Dokumente\\PitBoss R3E\\sessions.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_INDEX_PATH.write_text(json.dumps(idx, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

def parse_session_report_meta(path) -> dict:
    """0.2.15: Strecke/Fahrzeug/Runden/Bestzeit aus einem gespeicherten Report
    lesen. Fuellt aeltere Aufzeichnungen im Sitzungs-Browser nach, die noch
    keinen Eintrag in sessions.json hatten."""
    import re as _re
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    meta = {}
    m = _re.search(r"Track=([^|]+?)\s*\|", txt)
    if m:
        meta["track"] = m.group(1).strip()
    m = _re.search(r"Car=([^|]+?)\s*\|", txt)
    if m:
        meta["vehicle"] = m.group(1).strip()
    lap_rows = _re.findall(r"^\d+ \|\s*(?:REFERENZ|g\u00fcltig|ausgeschlossen|ung\u00fcltig \(einbezogen\))\s*\|", txt, _re.MULTILINE)
    if lap_rows:
        meta["runden"] = len(lap_rows)
    m = _re.search(r"Offizielle Bestzeit aus Scoring: ([\d:.]+)", txt)
    if m:
        meta["bestzeit"] = m.group(1).strip()
    else:
        times = _re.findall(r"^\d+ \|\s*(?:REFERENZ|g\u00fcltig)\s*\|.*?\|\s*(\d+:\d{2}\.\d{3})\s*\|", txt, _re.MULTILINE)
        if times:
            def _tsec(t):
                try:
                    mm, ss = t.split(":")
                    return int(mm) * 60 + float(ss)
                except Exception:
                    return 0.0
            meta["bestzeit"] = min(times, key=_tsec)
    return meta

def _csv_coerce_value(value, ftype):
    """0.2.17: CSV-Zellenwert passend zum Sample-Feldtyp umbauen."""
    raw = str(value if value is not None else "").strip()
    if ftype is bool:
        try:
            return float(raw) != 0.0
        except Exception:
            return False
    if ftype is int:
        try:
            return int(float(raw))
        except Exception:
            return 0
    if ftype is float:
        try:
            x = float(raw)
            return x if math.isfinite(x) else 0.0
        except Exception:
            return 0.0
    if ftype is tuple:
        return ()
    return raw  # str

def load_samples_from_csv(path):
    """0.2.17: gespeicherte PitBoss-CSV wieder in Sample-Objekte laden
    (Sitzungs-Browser: alte Aufzeichnung in die Ansicht laden).
    0.2.18: Ohne Return-Annotation - Sample ist erst weiter unten definiert."""
    hints = {f.name: f.type for f in _dc_fields(Sample)}
    out: List[Sample] = []
    with open(path, "r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            kwargs = {}
            for key, val in row.items():
                if key in hints:
                    kwargs[key] = _csv_coerce_value(val, hints[key])
            out.append(Sample(**kwargs))
    return out

# ---------------------------------------------------------------------------
class BetaFeedbackDialog(QDialog):
    """0.2.33/0.2.34: Beta-Tester-Formular fuer Bugs und Aenderungswuensche.

    Empfohlener Weg (0.2.34): 'Per E-Mail senden' - oeffnet das Mail-Programm
    mit einer fertig ausgefuellten E-Mail an den Entwickler (Betreff + Text
    inkl. Version und optionalem Log-Auszug). Nur noch 'Senden' klicken.
    Der komplette Text steht zusaetzlich in der Zwischenablage, falls das
    Mail-Programm den langen Text abschneidet.

    Alternative 1: 'In GitHub oeffnen' - vor-ausgefuelltes Issue im Browser.

    Alternative 2: 'Kopieren & speichern' - legt den Text in die
    Zwischenablage und als Datei unter Dokumente\\PitBoss R3E\\feedback\\ ab,
    der Ordner oeffnet sich direkt zum Weitergeben (Mail/Discord).
    """
    FEEDBACK_EMAIL = "pfoetiman76@hotmail.com"  # 0.2.34: Empfänger für Beta-Feedback

    CATEGORIES = (
        "Bug / Fehler",
        "Änderungswunsch",
        "Frage / Unklarheit",
    )

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.setWindowTitle("Beta-Feedback: Bug oder Änderungswunsch")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Kategorie:"))
        self.combo_cat = QComboBox()
        self.combo_cat.addItems(list(self.CATEGORIES))
        lay.addWidget(self.combo_cat)

        lay.addWidget(QLabel("Kurzer Titel (wird die Issue-Überschrift):"))
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("z. B. 'Report wird nicht gespeichert' oder 'Wunsch: Tastenkürzel für X'")
        lay.addWidget(self.edit_title)

        lay.addWidget(QLabel("Beschreibung – was ist passiert, was hast du erwartet, wie kann man es nachstellen?"))
        self.edit_desc = QTextEdit()
        self.edit_desc.setPlaceholderText("Je mehr Details (Strecke, Fahrzeug, was du gerade getan hast), desto leichter lässt es sich fixen.")
        lay.addWidget(self.edit_desc)

        self.chk_log = QCheckBox("Version + Log-Auszug (letzte 30 Zeilen) automatisch anhängen")
        self.chk_log.setChecked(True)
        lay.addWidget(self.chk_log)

        hint = QLabel("Empfohlen: 'Per E-Mail senden' – es öffnet sich dein Mail-Programm mit fertig ausgefüllter E-Mail, nur noch 'Senden' klicken. Alternativ 'In GitHub öffnen' (braucht GitHub-Account) oder 'Kopieren & speichern' für eine Feedback-Datei.")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.btn_email = QPushButton("Per E-Mail senden (empfohlen)")
        self.btn_email.clicked.connect(self._open_email)
        self.btn_github = QPushButton("In GitHub öffnen")
        self.btn_github.clicked.connect(self._open_github)
        self.btn_copy = QPushButton("Kopieren & als Datei speichern (offline)")
        self.btn_copy.clicked.connect(self._copy_and_save)
        self.btn_close = QPushButton("Schließen")
        self.btn_close.clicked.connect(self.reject)
        bb = QHBoxLayout()
        bb.addWidget(self.btn_email)
        bb.addWidget(self.btn_github)
        bb.addWidget(self.btn_copy)
        bb.addStretch(1)
        bb.addWidget(self.btn_close)
        lay.addLayout(bb)

    def feedback_text(self):
        from urllib.parse import quote as _quote  # noqa: F401 (siehe _open_github)
        cat = self.combo_cat.currentText()
        title = self.edit_title.text().strip()
        desc = self.edit_desc.toPlainText().strip()
        lines = [
            f"**Kategorie:** {cat}",
            f"**PitBoss R3E Version:** {APP_VERSION}",
        ]
        try:
            if getattr(self.main, "recording_signature", None):
                lines.append(f"**Zuletzt gefahren:** {self.main.sample_vehicle_label(self.main.recording_signature)}")
        except Exception:
            pass
        lines += ["", "**Beschreibung:**", desc or "(keine Beschreibung eingegeben)", ""]
        if self.chk_log.isChecked():
            try:
                log_txt = self.main.log.toPlainText().strip().splitlines()
                tail = "\n".join(log_txt[-30:]) if log_txt else "(Log leer)"
            except Exception:
                tail = "(Log nicht verfügbar)"
            lines += ["**Log-Auszug (letzte 30 Zeilen):**", "```", tail, "```", ""]
        return title, "\n".join(lines)

    def _open_email(self):
        """0.2.34: Standard-Mail-Programm mit fertig ausgefuellter Feedback-
        E-Mail oeffnen. Der Text liegt zusaetzlich in der Zwischenablage,
        falls mailto den langen Body (Log-Auszug) abschneidet."""
        from urllib.parse import quote as _quote
        title, body = self.feedback_text()
        if not title:
            QMessageBox.information(self, "Beta-Feedback", "Bitte vorher einen kurzen Titel eingeben.")
            return
        try:
            QApplication.clipboard().setText(body)
        except Exception:
            pass
        subject = f"[PitBoss R3E {APP_VERSION}] {self.combo_cat.currentText()}: {title}"
        # mailto-Bodies sind praktisch auf ~2000 Zeichen begrenzt: Log-Auszug
        # fuer die Mail kuerzen, voller Text steht ja in der Zwischenablage.
        mail_body = body
        if len(mail_body) > 1800:
            mail_body = mail_body[:1800] + "\n\n[... gekürzt – vollständiger Text liegt in der Zwischenablage und in der Log-Datei]"
        url = ("mailto:" + self.FEEDBACK_EMAIL
               + "?subject=" + _quote(subject)
               + "&body=" + _quote(mail_body))
        QDesktopServices.openUrl(QUrl(url))
        self.main.log.append("Beta-Feedback: E-Mail an " + self.FEEDBACK_EMAIL + " vorbereitet (Kategorie: " + self.combo_cat.currentText() + ", voller Text in der Zwischenablage).")

    def _open_github(self):
        from urllib.parse import quote as _quote
        title, body = self.feedback_text()
        if not title:
            QMessageBox.information(self, "Beta-Feedback", "Bitte vorher einen kurzen Titel eingeben.")
            return
        url = ("https://github.com/Pfoetiman76/pitboss-r3e/issues/new"
               "?title=" + _quote(title) + "&body=" + _quote(body) + "&labels=beta-feedback")
        QDesktopServices.openUrl(QUrl(url))
        self.main.log.append("Beta-Feedback: GitHub-Issue im Browser geöffnet (Kategorie: " + self.combo_cat.currentText() + ").")

    def _copy_and_save(self):
        from urllib.parse import quote as _quote  # noqa: F401
        title, body = self.feedback_text()
        try:
            QApplication.clipboard().setText(body)
        except Exception:
            pass
        try:
            FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = FEEDBACK_DIR / f"feedback_{stamp}.txt"
            path.write_text(body, encoding="utf-8")
            self.main.log.append(f"Beta-Feedback gespeichert (auch in der Zwischenablage): {path.resolve()}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(FEEDBACK_DIR.resolve())))
            QMessageBox.information(self, "Beta-Feedback", "Feedback-Datei gespeichert und Text in die Zwischenablage kopiert.\n\nDatei liegt in:\n" + str(FEEDBACK_DIR.resolve()))
        except Exception as e:
            QMessageBox.warning(self, "Beta-Feedback", f"Speichern fehlgeschlagen ({type(e).__name__}: {e}).\nDer Text liegt aber in der Zwischenablage.")


# ---------------------------------------------------------------------------
# 0.2.5: Frei belegbare Hotkey-Liste. Standard ist F6-F12 wie bisher; jede Aktion
# kann im Dialog "Hotkeys belegen ..." auf F1-F24 oder 0-9 geändert werden.
# Unter Windows laufen die Hotkeys weiterhin ueber das globale Tastatur-Polling
# (GetAsyncKeyState), damit sie auch funktionieren, waehrend RaceRoom im Fokus ist.
# ---------------------------------------------------------------------------
HOTKEY_ACTIONS = [
    ("tire_overlay", "Reifen-Overlay"),
    ("auto_bestlap", "Auto-Bestlap AN/AUS"),
    ("record", "Recording Start/Stop"),
    ("snapshot", "Snapshot"),
    ("overlay", "Coach-Overlay"),
    ("live_coach", "Live-Coach"),
    ("brake_coach", "Kurven-Coach"),
    ("corner_overlay", "Kurven-Namen-Overlay"),
]
DEFAULT_HOTKEYS = {
    "tire_overlay": "F6", "auto_bestlap": "F7", "record": "F8", "snapshot": "F9",
    "overlay": "F10", "live_coach": "F11", "brake_coach": "F12",
    "corner_overlay": "F5",
}
HOTKEY_ACTION_KEYS = [a for a, _label in HOTKEY_ACTIONS]
SUPPORTED_HOTKEY_KEYS = [f"F{i}" for i in range(1, 25)] + [str(d) for d in range(10)]


def hotkey_vk(key: str) -> Optional[int]:
    """0.2.5: Windows-Virtual-Key-Code fuer eine unterstuetzte Hotkey-Taste."""
    key = str(key or "").strip().upper()
    if key.startswith("F") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)  # VK_F1..VK_F24
    if key.isdigit():
        return 0x30 + int(key)  # VK_0..VK_9
    return None


def load_hotkey_config() -> dict:
    """0.2.5: Hotkey-Belegung laden (ungueltige/fehlende Eintraege -> Standard)."""
    cfg = dict(DEFAULT_HOTKEYS)
    try:
        raw = json.loads(HOTKEY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = None
    if isinstance(raw, dict):
        for action in HOTKEY_ACTION_KEYS:
            key = str(raw.get(action, "")).strip().upper()
            if key in SUPPORTED_HOTKEY_KEYS:
                cfg[action] = key
    used = set()
    for action in HOTKEY_ACTION_KEYS:  # Doppelbelegungen aus alter Config entfernen
        if cfg[action] in used:
            cfg[action] = DEFAULT_HOTKEYS[action]
        used.add(cfg[action])
    return cfg


def save_hotkey_config(cfg: dict):
    """0.2.5: Hotkey-Belegung in Dokumente\\PitBoss R3E\\hotkeys.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        HOTKEY_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def hotkey_summary(cfg: dict) -> str:
    """0.2.5: 'Aktion Taste'-Liste fuer Report/Log."""
    return " | ".join(f"{cfg.get(a, DEFAULT_HOTKEYS[a])} {label}" for a, label in HOTKEY_ACTIONS)


for _d in (EXPORT_DIR, REPORT_DIR, CSV_DIR, REFERENCE_DIR, PROFILE_ASSET_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
ASSET_DIR = APP_DIR / "assets"

# ---------------------------------------------------------------------------
# 0.2.0: Design im RaceRoom-Stil. Anthrazit/Schwarz, eckige Kanten, rote Akzente.
# Ein Template, zwei Paletten. Pfade zu den Pfeil-Icons werden absolut eingesetzt
# (relative url() hing vom Arbeitsverzeichnis ab).
# ---------------------------------------------------------------------------
RR_RED = "#e8212b"
_QSS_PALETTES = {
    "dark": {
        "BG": "#0c0c0e", "PANEL": "#131316", "PANEL2": "#1a1a1f", "INPUT": "#15151a",
        "LINE": "#26262c", "LINE2": "#34343c", "TEXT": "#f1f1f3", "MUTED": "#8f8f99",
        "BAR": "#101013", "HOVER": "#1c1c21", "ACC": RR_RED, "ACC_H": "#ff3a45", "ACC_D": "#a81119",
        "SCROLL": "#34343c", "ARROW": "arrow_down_light.svg", "ACC_TXT": "#ff5a63",
        "SEL": "rgba(232,33,43,0.85)",
        "BG1": "#3a1c21", "BG2": "#1d1c20", "BG3": "#111113", "TOPBAR": "rgba(8,8,10,0.55)",
        "CARD": "rgba(12,12,15,0.74)", "TILE_A": "rgba(44,44,49,0.90)", "TILE_B": "rgba(12,12,15,0.94)",
        "NAV": "rgba(52,51,56,0.92)", "NAV_TXT": "#d9d9de", "NAV_H": "rgba(80,79,86,0.96)",
        "NAV_ON": "#ffffff", "NAV_ON_TXT": "#101013",
        "BTN": "rgba(52,51,56,0.92)", "BTN_H": "rgba(80,79,86,0.96)", "BTN_B": "rgba(255,255,255,0.07)",
        "HERO_A": "#8a1219", "HERO_B": "#1b0f12",
    },
    "light": {
        "BG": "#ececef", "PANEL": "#ffffff", "PANEL2": "#f3f3f6", "INPUT": "#ffffff",
        "LINE": "#d4d4da", "LINE2": "#b9b9c2", "TEXT": "#16161a", "MUTED": "#666671",
        "BAR": "#ffffff", "HOVER": "#f0f0f4", "ACC": RR_RED, "ACC_H": "#ff3a45", "ACC_D": "#a81119",
        "SCROLL": "#c2c2cb", "ARROW": "arrow_down_dark.svg", "ACC_TXT": "#c4151f",
        "SEL": "rgba(232,33,43,0.85)",
        "BG1": "#f6f1f2", "BG2": "#e9e9ee", "BG3": "#dcdce2", "TOPBAR": "rgba(255,255,255,0.80)",
        "CARD": "rgba(255,255,255,0.88)", "TILE_A": "rgba(255,255,255,0.96)", "TILE_B": "rgba(238,238,243,0.96)",
        "NAV": "rgba(214,214,221,0.95)", "NAV_TXT": "#2a2a30", "NAV_H": "#c4c4cd",
        "NAV_ON": "#16161a", "NAV_ON_TXT": "#ffffff",
        "BTN": "#e4e4ea", "BTN_H": "#d4d4dc", "BTN_B": "#c9c9d2",
        "HERO_A": "#8a1219", "HERO_B": "#1b0f12",
    },
}

_QSS_TEMPLATE = """
QWidget { font-family: "Montserrat", "Segoe UI", "Inter", sans-serif; font-size: 13px; color: @TEXT@; }
QMainWindow, QWidget { background: @BG@; }
QWidget#rootBg { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @BG1@, stop:0.5 @BG2@, stop:1 @BG3@); }
QWidget[plain="true"], QTabWidget, QStackedWidget, QTabBar { background: transparent; }
QLabel { background: transparent; color: @TEXT@; }
QFrame#topBar { background: @TOPBAR@; border: none; border-radius: 0; }
QFrame#navBar { background: transparent; border: none; }
QLabel#brandTitle { font-size: 19px; font-weight: 800; color: @TEXT@; background: transparent; }
QLabel#brandSub { font-size: 11px; color: @MUTED@; background: transparent; }
QLabel#connPill { background: @PANEL2@; border: 1px solid @LINE2@; border-radius: 2px; padding: 5px 12px; font-weight: 700; font-size: 12px; }
QLabel#connPill[state="on"] { border-color: #3fb950; color: #3fb950; }
QLabel#connPill[state="rec"] { border-color: @ACC@; color: @ACC_TXT@; }
QLabel#statusLine { color: @MUTED@; font-size: 12px; padding: 2px 2px 6px 2px; background: transparent; }
QLabel#sectionTitle { font-size: 11px; font-weight: 800; color: @MUTED@; background: transparent; padding-top: 6px; }
QLabel#hint { color: @MUTED@; font-size: 12px; background: transparent; }
QLabel#verLabel { color: @MUTED@; font-size: 11px; background: transparent; padding: 0 4px; }
QPushButton#navBtn { padding: 0 22px; min-height: 44px; max-height: 44px; border: none; border-radius: 0; background: @NAV@; color: @NAV_TXT@; font-weight: 600; font-size: 12px; }
QPushButton#navBtn:hover { background: @NAV_H@; color: @NAV_TXT@; }
QPushButton#navBtn:checked { background: @NAV_ON@; color: @NAV_ON_TXT@; }
QPushButton#navArrow { padding: 0; min-width: 40px; max-width: 40px; min-height: 44px; max-height: 44px; border: none; border-radius: 0; background: @NAV@; color: @NAV_TXT@; font-size: 20px; font-weight: 400; }
QPushButton#navArrow:hover { background: @NAV_H@; }
QPushButton#navArrow:disabled { background: transparent; color: @MUTED@; }
QTabWidget::pane { border: none; border-top: 1px solid @LINE@; background: transparent; top: -1px; }
QTabBar::tab { background: transparent; color: @MUTED@; padding: 9px 18px; margin-right: 2px; border: none; border-bottom: 2px solid transparent; font-weight: 700; }
QTabBar::tab:hover { color: @TEXT@; }
QTabBar::tab:selected { color: @TEXT@; border-bottom: 2px solid @ACC@; }
QGroupBox { border: 1px solid @BTN_B@; border-radius: 2px; margin-top: 14px; padding: 12px; font-weight: 700; background: @CARD@; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: @MUTED@; }
QPushButton { background: @BTN@; color: @TEXT@; border: 1px solid @BTN_B@; padding: 8px 16px; border-radius: 0; font-weight: 700; }
QPushButton:hover { border-color: @ACC@; background: @BTN_H@; }
QPushButton:pressed { background: @BG@; }
QPushButton:disabled { color: @MUTED@; background: @PANEL@; border-color: @LINE@; }
QPushButton#primary { background: @ACC@; color: #ffffff; border: 1px solid @ACC@; padding: 9px 20px; }
QPushButton#primary:hover { background: @ACC_H@; border-color: @ACC_H@; }
QPushButton#primary:pressed { background: @ACC_D@; }
QPushButton#recBtn { background: @ACC@; color: #ffffff; border: 1px solid @ACC@; padding: 9px 22px; font-size: 13px; font-weight: 800; }
QPushButton#recBtn:hover { background: @ACC_H@; border-color: @ACC_H@; }
QPushButton#recBtn[rec="true"] { background: @BG@; color: @ACC_TXT@; border: 2px solid @ACC@; padding: 8px 21px; }
QTextEdit, QLineEdit, QTableWidget, QComboBox, QSpinBox { background: @INPUT@; color: @TEXT@; border: 1px solid @LINE@; border-radius: 2px; selection-background-color: @ACC@; selection-color: #ffffff; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus { border: 1px solid @ACC@; }
QComboBox { padding: 3px 30px 3px 10px; min-height: 30px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: right center; width: 26px; border: none; border-left: 1px solid @LINE@; background: @PANEL2@; }
QComboBox::drop-down:hover { background: @ACC@; }
QComboBox::down-arrow { image: url(@ASSETS@/@ARROW@); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @PANEL@; color: @TEXT@; selection-background-color: @ACC@; selection-color: #ffffff; outline: 0; border: 1px solid @LINE2@; padding: 2px; }
QSpinBox { min-height: 28px; padding: 2px 6px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid @LINE2@; background: @INPUT@; border-radius: 2px; }
QCheckBox::indicator:checked { background: @ACC@; border-color: @ACC@; }
QTableWidget { gridline-color: @LINE@; alternate-background-color: @PANEL@; border-radius: 2px; }
QHeaderView::section { background: @PANEL2@; color: @MUTED@; padding: 7px 8px; border: none; border-bottom: 1px solid @LINE2@; font-weight: 700; }
QTableWidget::item:selected { background: @SEL@; color: #ffffff; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: @SCROLL@; border-radius: 2px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @ACC@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: @SCROLL@; border-radius: 2px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: @ACC@; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMenu { background: @PANEL@; color: @TEXT@; border: 1px solid @LINE2@; padding: 4px; }
QMenu::item { padding: 8px 24px; border-radius: 0; }
QMenu::item:selected { background: @ACC@; color: #ffffff; }
QMenu::separator { height: 1px; background: @LINE@; margin: 4px 8px; }
QToolButton { background: @BTN@; color: @TEXT@; border: 1px solid @BTN_B@; padding: 8px 14px; border-radius: 0; font-weight: 700; }
QToolButton:hover { border-color: @ACC@; background: @BTN_H@; }
QToolButton::menu-indicator { image: none; }
QToolTip { background: @PANEL@; color: @TEXT@; border: 1px solid @LINE2@; padding: 5px; }
QFrame#dashCard { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @TILE_A@, stop:1 @TILE_B@); border: 1px solid @BTN_B@; border-bottom: 2px solid @ACC@; border-radius: 0; }
QLabel#dashCardKey { color: @MUTED@; font-size: 11px; font-weight: 700; background: transparent; }
QLabel#dashCardVal { color: @TEXT@; font-size: 18px; font-weight: 800; background: transparent; }
QFrame#linkCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @HERO_A@, stop:0.55 @HERO_B@, stop:1 @HERO_B@); border: 1px solid @BTN_B@; border-radius: 0; }
QFrame#linkCard:hover { border: 1px solid @ACC@; }
QLabel#linkCardTitle { color: #ffffff; font-size: 22px; font-weight: 800; background: transparent; }
QLabel#linkCardSub { color: #e6c9cc; font-size: 11px; font-weight: 700; background: transparent; }
QLabel#linkCardArrow { color: #ffffff; font-size: 26px; font-weight: 400; background: transparent; }
QLabel#accentValue { color: @ACC_TXT@; font-size: 15px; font-weight: 800; background: transparent; }
"""


def _build_qss(mode: str) -> str:
    pal = _QSS_PALETTES["light" if mode == "light" else "dark"]
    q = _QSS_TEMPLATE
    for k, v in pal.items():
        q = q.replace("@%s@" % k, v)
    return q.replace("@ASSETS@", ASSET_DIR.as_posix())


DARK_QSS = _build_qss("dark")
LIGHT_QSS = _build_qss("light")




def qt_message_filter(mode, context, message):
    """Suppress harmless Qt font warning seen on some Windows systems.
    Keeps all other Qt messages visible.
    """
    try:
        msg = str(message)
        if "QFont::setPointSize: Point size <= 0" in msg:
            return
        print(msg, file=sys.stderr)
    except Exception:
        pass


def dec(b) -> str:
    try:
        return bytes(b).split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        try:
            return bytes(b).split(b"\x00", 1)[0].decode("latin1", errors="ignore").strip()
        except Exception:
            return ""


def fnum(v, default=0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default



def fmt_lap_time(seconds: float, signed: bool = False) -> str:
    """Format absolute lap/sector times as [m]:ss.000, e.g. 1:54.321.
    For signed=True, keeps +/- in front of the formatted absolute value.
    """
    try:
        x = float(seconds)
    except Exception:
        return "-"
    if not math.isfinite(x) or x < -900:
        return "-"
    sign = ""
    if signed:
        if x > 0:
            sign = "+"
        elif x < 0:
            sign = "-"
        x = abs(x)
    elif x < 0:
        return "-"
    minutes = int(x // 60)
    rest = x - minutes * 60
    return f"{sign}{minutes}:{rest:06.3f}"




def parse_lap_time_to_seconds(text) -> float:
    """Accepts 3:33.177, 213.177, 03:33,177 or strings containing a lap time."""
    if text is None:
        return 0.0
    raw = str(text).strip().replace(',', '.')
    if not raw:
        return 0.0
    import re
    m = re.search(r'(\d{1,2})\s*[:;]\s*(\d{1,2}(?:\.\d{1,3})?)', raw)
    if m:
        return int(m.group(1)) * 60.0 + float(m.group(2))
    m = re.search(r'\b(\d{2,4}(?:\.\d{1,3})?)\b', raw)
    if m:
        val = float(m.group(1))
        return val if 20.0 <= val <= 1800.0 else 0.0
    return 0.0


def normalize_match_text(text: str) -> str:
    txt = (text or '').lower()
    keep = []
    for ch in txt:
        keep.append(ch if ch.isalnum() else ' ')
    return ' '.join(''.join(keep).split())

def grip_label_from_score(score: float) -> str:
    try:
        x = float(score)
    except Exception:
        x = 0.0
    if x >= 92:
        return "perfekt"
    if x >= 80:
        return "hoch"
    if x >= 60:
        return "mittel"
    return "niedrig"


# Vom Spiel (RaceRoom) gelieferte Temperaturfenster der Reifen; 0 = unbekannt -> feste Schwellen.
_TIRE_TEMP_WINDOW = {"cold": 0.0, "opt": 0.0, "hot": 0.0}


def set_tire_temp_window(cold: float, opt: float, hot: float) -> None:
    """Wird pro Live-Tick aus dem Sample gesetzt, damit alle Reifenfarben das echte Fenster des Autos nutzen."""
    try:
        cold, opt, hot = float(cold), float(opt), float(hot)
    except Exception:
        return
    if 0.0 < cold < hot:
        _TIRE_TEMP_WINDOW["cold"], _TIRE_TEMP_WINDOW["opt"], _TIRE_TEMP_WINDOW["hot"] = cold, opt, hot


def temp_color_for_tire(temp_c: float) -> QColor:
    try:
        t = float(temp_c)
    except Exception:
        t = 0.0
    if t <= 0:
        return QColor(70, 95, 120)
    cold, hot = _TIRE_TEMP_WINDOW["cold"], _TIRE_TEMP_WINDOW["hot"]
    if 0.0 < cold < hot:
        span = hot - cold
        if t < cold - 0.25 * span:
            return QColor(60, 160, 255)      # kalt / blau (wie RaceRoom-HUD)
        if t < cold:
            return QColor(90, 215, 215)      # Uebergang / tuerkis
        if t <= hot:
            return QColor(60, 215, 90)       # im Fenster / gruen
        if t <= hot + 0.25 * span:
            return QColor(255, 165, 40)      # warm / orange
        return QColor(240, 55, 45)           # heiss / rot
    if t < 55:
        return QColor(60, 160, 255)      # kalt / blau
    if t < 70:
        return QColor(90, 215, 215)      # Übergang / türkis
    if t <= 95:
        return QColor(60, 215, 90)       # optimal / grün
    if t <= 110:
        return QColor(255, 165, 40)      # warm / orange
    return QColor(240, 55, 45)           # heiß / rot

def infer_vehicle_class(vehicle_class: str, vehicle_name: str = "", vehicle_model: str = "") -> str:
    """RaceRoom liefert die Klasse als Klartext (z. B. "GTR 3", "DTM 2023", "Group C") -
    wird unveraendert uebernommen. ABS/Non-ABS entscheidet NICHT die Klasse, sondern Sample.abs_on."""
    return (vehicle_class or "Unbekannt").strip() or "Unbekannt"


# 0.5.9.21: Breites Tier-Format der "Ohne Speed's - RaceRoom laptimes"-Tabelle
# (eine Zeile pro Strecke/Klasse mit 8 Skill-Tier-Zeitspalten: Alien, Competitive,
# Good x2, Midpack x2, Tail-ender, Offline). Ergaenzt den bestehenden flachen
# Personal-Reference-Parser additiv, ersetzt ihn nicht.


def safe_filename_part(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (text or "").strip())
    return cleaned.strip("_") or "unknown"


@dataclass
class Sample:
    timestamp: str
    game_version: int
    track: str
    player_name: str
    active_vehicles: int
    player_idx: int
    player_has_vehicle: bool
    telem_id: int
    scoring_id: int
    vehicle_name: str
    vehicle_model: str
    vehicle_class: str
    speed_kmh: float
    gear: int
    rpm: float
    fuel_l: float
    fuel_capacity_l: float
    throttle: float
    brake: float
    steering: float
    pos_x: float
    pos_y: float
    pos_z: float
    lap_number: int
    completed_laps: int
    lap_dist_m: float
    current_lap_time: float
    last_lap_time: float
    best_lap_time: float
    lap_invalidated: bool
    in_pits: bool
    place: int
    tire_fl_pressure_kpa: float = 0.0
    tire_fr_pressure_kpa: float = 0.0
    tire_rl_pressure_kpa: float = 0.0
    tire_rr_pressure_kpa: float = 0.0
    tire_fl_temp_l_c: float = 0.0
    tire_fl_temp_c_c: float = 0.0
    tire_fl_temp_r_c: float = 0.0
    tire_fr_temp_l_c: float = 0.0
    tire_fr_temp_c_c: float = 0.0
    tire_fr_temp_r_c: float = 0.0
    tire_rl_temp_l_c: float = 0.0
    tire_rl_temp_c_c: float = 0.0
    tire_rl_temp_r_c: float = 0.0
    tire_rr_temp_l_c: float = 0.0
    tire_rr_temp_c_c: float = 0.0
    tire_rr_temp_r_c: float = 0.0
    tire_fl_carcass_c: float = 0.0
    tire_fr_carcass_c: float = 0.0
    tire_rl_carcass_c: float = 0.0
    tire_rr_carcass_c: float = 0.0
    tire_fl_wear_pct: float = 0.0
    tire_fr_wear_pct: float = 0.0
    tire_rl_wear_pct: float = 0.0
    tire_rr_wear_pct: float = 0.0
    tire_fl_flat: bool = False
    tire_fr_flat: bool = False
    tire_rl_flat: bool = False
    tire_rr_flat: bool = False
    tire_fl_grip_fract: float = 0.0
    tire_fr_grip_fract: float = 0.0
    tire_rl_grip_fract: float = 0.0
    tire_rr_grip_fract: float = 0.0
    accel_lat_ms2: float = 0.0
    accel_long_ms2: float = 0.0
    session_type: int = 0  # 0.4.8.8: mSession (0 testday,1-4 practice,5-8 qual,9 warmup,10-13 race)
    path_lateral_m: float = 0.0  # 0.4.8.9: seitlicher Abstand zur (groben) Mittellinie
    track_edge_m: float = 0.0    # 0.4.8.9: Streckenrand auf der Fahrzeugseite
    session_remaining_s: float = 0.0
    session_current_et: float = 0.0     # 0.4.9.5
    session_end_et: float = 0.0
    sector_index: int = 0            # 0.4.9.0: mSector (0=S3, 1=S1, 2=S2)
    cur_sector1_s: float = 0.0
    cur_sector2_s: float = 0.0
    last_sector1_s: float = 0.0
    last_sector2_s: float = 0.0
    best_sector1_s: float = 0.0
    best_sector2_s: float = 0.0
    brake_fl_temp_raw: float = 0.0   # 0.4.9.0: brake_temp roh (K oder C, Erkennung im Overlay)
    brake_fr_temp_raw: float = 0.0
    brake_rl_temp_raw: float = 0.0
    brake_rr_temp_raw: float = 0.0
    max_rpm: float = 0.0             # 0.4.9.0
    virtual_energy: float = 0.0
    ffb_torque: float = 0.0          # 0.4.9.0: generic.FFBTorque
    steering_shaft_torque: float = 0.0
    pit_state: int = 0               # 0.4.9.1: 0 keine,1 angefordert,2 Einfahrt,3 steht,4 Ausfahrt
    speed_limiter: bool = False
    num_pitstops: int = 0
    gap_ahead_s: float = 0.0         # 0.4.9.1: Abstand nach vorn
    gap_behind_s: float = 0.0
    gap_leader_s: float = 0.0
    laps_behind_next: int = 0
    laps_behind_leader: int = 0
    rear_brake_bias: float = 0.0     # 0.4.9.1
    brake_fl_pressure: float = 0.0
    brake_fr_pressure: float = 0.0
    brake_rl_pressure: float = 0.0
    brake_rr_pressure: float = 0.0
    tire_fl_slip_ms: float = 0.0
    tire_fr_slip_ms: float = 0.0
    tire_rl_slip_ms: float = 0.0
    tire_rr_slip_ms: float = 0.0
    # 0.4.7.1: Roh-Fahrereingabe (unfiltered) fuer das Pedal-Input-Overlay
    input_throttle: float = 0.0
    input_brake: float = 0.0
    input_clutch: float = 0.0
    input_steering: float = 0.0  # 0.4.7.1: Roh-Lenkeingabe (-1..1) fuer Pedal-/Lenk-Trace
    opponents: tuple = ()  # 0.4.9.9 Spotter: ((mID, x, z, in_pits), ...) Weltkoordinaten
    opponents_behind: tuple = ()  # 0.5.1.0 Ueberholalarm: ((place, driver, vclass, dist_m), ...)
    game_phase: int = 0            # 0.5.1.0 Flaggen
    yellow_flag_state: int = 0
    player_flag: int = 0
    abs_on: bool = False              # RaceRoom: aid_settings.abs >= 1 (ABS an bzw. aktiv)
    dmg_engine_pct: float = -1.0      # RaceRoom car_damage als Schaden in % (-1 = nicht verfuegbar)
    dmg_transmission_pct: float = -1.0
    dmg_aero_pct: float = -1.0
    dmg_suspension_pct: float = -1.0
    tire_temp_cold_c: float = 0.0     # vom Spiel gelieferte Reifen-Temperaturfenster (0 = unbekannt)
    tire_temp_opt_c: float = 0.0
    tire_temp_hot_c: float = 0.0
    pit_window_status: int = -1       # RaceRoom: 0 aus, 1 zu, 2 offen, 3 Stopp laeuft, 4 erledigt
    pit_elapsed_s: float = -1.0
    pit_total_s: float = -1.0
    track_length_m: float = 0.0       # 0.2.9: layout_length aus dem Spiel (0 = unbekannt)
    layout_id: int = 0                   # 0.2.38: Layout-ID aus dem Spiel fuer echte Kurvennamen
    sector_bounds_m: tuple = ()       # 0.2.9: offizielle innere Sektorgrenzen in m (S1-Ende, S2-Ende); leer = unbekannt
    # 0.2.20: zusaetzliche Telemetrie-Kanaele (Reader -> Sample -> CSV)
    g_force_lat: float = 0.0          # 0.2.20: Quer-G-Kraft (mLocalGForce.x)
    g_force_long: float = 0.0          # 0.2.20: Laengs-G-Kraft (mLocalGForce.z)
    heading_deg: float = 0.0           # 0.2.20: Fahrtrichtung in Grad (Gierrate-Yaw)
    velocity_lat_ms: float = 0.0       # 0.2.20: seitliche Geschwindigkeit m/s
    velocity_long_ms: float = 0.0      # 0.2.20: laengs Geschwindigkeit m/s (Vorzeichen)
    engine_torque_nm: float = 0.0      # 0.2.20: Motordrehmoment Nm
    tc_on: bool = False                # 0.2.20: Traktionskontrolle aktiv (aid_settings.tc >= 1)
    esp_on: bool = False               # 0.2.20: ESP aktiv (aid_settings.esp >= 1)




@dataclass
class LapSummary:
    lap_number: int
    samples: int
    valid_samples: int
    start_m: float
    end_m: float
    coverage_m: float
    duration_s: float
    min_speed: float
    max_speed: float
    avg_speed: float
    max_brake: float
    avg_throttle: float
    fuel_start_l: float
    fuel_end_l: float
    fuel_used_l: float
    invalidated: bool
    in_pits: bool
    has_standstill: bool
    is_complete: bool
    is_clean: bool
    reason: str


@dataclass
class SegmentSummary:
    lap_number: int
    start_m: int
    end_m: int
    samples: int
    seg_time_s: float
    avg_speed: float
    min_speed: float
    max_speed: float
    max_brake: float
    avg_throttle: float
    gear_common: str


@dataclass
class SegmentDelta:
    start_m: int
    end_m: int
    compare_lap: int
    reference_lap: int
    cmp_time_s: float
    ref_time_s: float
    delta_s: float
    cmp_avg_speed: float
    ref_avg_speed: float
    speed_delta: float
    cmp_max_brake: float
    ref_max_brake: float
    brake_delta: float
    cmp_avg_throttle: float
    ref_avg_throttle: float
    throttle_delta: float
    hint: str


class TelemetryMapWidget(QWidget):
    """0.2.25: Input-Streckenkarte im MoTeC-Stil - die gefahrene Linie ist
    nach Input gefaerbt: gruen = Gas, rot = Bremse, grau = rollen/Teilgas.
    Zeigt, WO auf der Strecke was am Pedal passiert."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.outline = []  # 0.2.26: Strecken-Umriss aus allen Runden, damit die Karte lesbar bleibt
        self.cursor_dist = None  # 0.2.27: None = automatisch letzte Position, sonst Rundenmeter
        self.setMinimumHeight(220)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self.update()

    def set_outline(self, rows):
        self.outline = list(rows or [])
        self.update()

    def set_cursor_dist(self, d):
        if d != self.cursor_dist:
            self.cursor_dist = d
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(16, 16, 16))
        rows = self.rows
        if len(rows) < 2:
            p.setPen(QColor(200, 200, 205))
            p.drawText(self.rect(), Qt.AlignCenter, "Input-Karte erscheint mit aufgezeichneter Fahrt")
            return
        w, h = self.width(), self.height()
        base = self.outline if len(self.outline) >= 2 else rows
        # 0.2.28: gleiche Achsen wie die Heatmap-Karte - pos_x/pos_z, z nach oben gespiegelt
        xs = [float(s.pos_x) for s in base]
        zs = [float(s.pos_z) for s in base]
        minx, maxx = min(xs), max(xs)
        minz, maxz = min(zs), max(zs)
        span = max(maxx - minx, maxz - minz, 1.0)
        pad = 24.0
        scale = max(min(w, h) - 2 * pad, 40.0)

        def pt(s):
            x = pad + (float(s.pos_x) - minx) / span * scale + max(0.0, (w - 2 * pad - scale) / 2.0)
            y = pad + (maxz - float(s.pos_z)) / span * scale + max(0.0, (h - 2 * pad - scale) / 2.0)
            return (x, y)

        # 0.2.26: Strecken-Umriss zuerst (duenn, grau), damit die Karte lesbar bleibt
        if len(self.outline) >= 2:
            prev = None
            p.setPen(QPen(QColor(85, 85, 92), 2))
            for s in self.outline:
                x, y = pt(s)
                if prev is not None and abs(x - prev[0]) + abs(y - prev[1]) < 400:
                    p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
                prev = (x, y)
        prev = None
        for s in rows:
            x, y = pt(s)
            if prev is not None:
                if abs(x - prev[0]) + abs(y - prev[1]) < 400:  # Sprung Start/Ziel abfangen
                    if float(s.brake) > 0.08:
                        col = QColor(220, 60, 50)      # Bremse
                    elif float(s.throttle) > 0.5:
                        col = QColor(80, 200, 100)      # Gas
                    else:
                        col = QColor(120, 120, 128)    # rollen / Teilgas
                    p.setPen(QPen(col, 4))
                    p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
            prev = (x, y)
        x0, y0 = pt(rows[0])  # Start/Ziel-Marker
        p.setPen(QPen(QColor(235, 185, 60), 2))
        p.drawEllipse(QPointF(x0, y0), 4, 4)
        # 0.2.26/0.2.27: Position als gelber Punkt - automatisch am Ende oder am Cursor (Maus)
        pos_s = rows[-1]
        if self.cursor_dist is not None:
            best = None
            for s in rows:
                d = abs(float(getattr(s, "lap_dist_m", 0.0) or 0.0) - float(self.cursor_dist))
                if best is None or d < best[0]:
                    best = (d, s)
            if best is not None:
                pos_s = best[1]
        cur = pt(pos_s)
        p.setPen(QPen(QColor(235, 185, 60), 2))
        p.drawEllipse(QPointF(cur[0], cur[1]), 7, 7)
        p.setPen(QPen(QColor(16, 16, 16), 2))
        p.drawEllipse(QPointF(cur[0], cur[1]), 3, 3)
        p.setPen(QColor(150, 150, 158))
        p.drawText(QRectF(8, 4, 400, 16), Qt.AlignLeft, "Input-Karte: gruen = Gas, rot = Bremse, grau = rollen")


class TelemetryTraceWidget(QWidget):
    """0.2.24: MoTeC-i2-Stil - Kanaele ueber Rundenmeter: Throttle (gruen) und
    Brake (rot) von 0..100%, darunter Steering zentriert, mit Raster und Achsen."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.cursor_dist = None  # 0.2.27: Rundenmeter des Cursors; None = automatisch am Ende folgen
        self.on_cursor = None    # 0.2.27: Callback(dist) wenn der Nutzer den Cursor zieht
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self.update()

    def set_cursor_dist(self, d):
        if d != self.cursor_dist:
            self.cursor_dist = d
            self.update()

    def mousePressEvent(self, e):
        self._cursor_from_pos(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._cursor_from_pos(e)

    def _cursor_from_pos(self, e):
        """0.2.27: Cursor per Maus ziehen - gelber Streifen ist interaktiv."""
        if len(self.rows) < 2 or not self.on_cursor:
            return
        left = 86
        plot_w = max(self.width() - left - 8, 1.0)
        frac = max(0.0, min(1.0, (float(e.position().x()) - left) / plot_w))
        dmax = 1.0
        for s in self.rows:
            d = float(getattr(s, "lap_dist_m", 0.0) or 0.0)
            if d > dmax:
                dmax = d
        self.on_cursor(frac * dmax)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(16, 16, 16))
        rows = self.rows
        if len(rows) < 2:
            p.setPen(QColor(200, 200, 205))
            p.drawText(self.rect(), Qt.AlignCenter, "Pedale und Lenkung erscheinen mit aufgezeichneter Fahrt")
            return
        w, h = self.width(), self.height()
        left = 86
        dmax = 1.0
        for s in rows:
            d = float(getattr(s, "lap_dist_m", 0.0) or 0.0)
            if d > dmax:
                dmax = d
        if dmax <= 0:
            dmax = 1.0
        plot_w = w - left - 8

        def px(s):
            return left + (float(getattr(s, "lap_dist_m", 0.0) or 0.0) / dmax) * plot_w

        lane_h = h / 2.0
        pedal_top, pedal_h = 20, lane_h - 26  # 0..100%
        steer_mid = lane_h + lane_h / 2.0  # zentriert +-1
        steer_amp = lane_h / 2.0 - 20.0
        # Raster wie MoTeC: vertikal alle 10% Distanz, horizontal Viertel
        p.setPen(QPen(QColor(56, 56, 60), 1))
        for k in range(1, 10):
            x = left + plot_w * k / 10.0
            p.drawLine(int(x), 20, int(x), h - 2)
        for k in range(1, 4):
            y = pedal_top + pedal_h * k / 4.0
            p.drawLine(left, int(y), w - 8, int(y))
        p.setPen(QPen(QColor(90, 90, 96), 1))
        p.drawLine(left, int(steer_mid), w - 8, int(steer_mid))
        p.setPen(QPen(QColor(90, 90, 96), 2))
        p.drawLine(left, int(pedal_top + pedal_h), w - 8, int(pedal_top + pedal_h))  # Nulllinie Pedale
        # Achsen-Labels (MoTeC-Stil: links)
        p.setPen(QColor(150, 150, 158))
        p.drawText(QRectF(4, pedal_top - 2, left - 10, 14), Qt.AlignRight, "100%")
        p.drawText(QRectF(4, pedal_top + pedal_h - 12, left - 10, 14), Qt.AlignRight, "0%")
        p.drawText(QRectF(4, steer_mid - 8, left - 10, 14), Qt.AlignRight, "0")
        p.drawText(QRectF(left, 2, 260, 16), Qt.AlignLeft, "Throttle / Brake")
        p.drawText(QRectF(left, lane_h, 260, 16), Qt.AlignLeft, "Steering")
        # Kurven: Throttle gruen, Brake rot (beide 0..100% nach oben)
        for col, f in (
            (QColor(80, 200, 100), lambda s: float(s.throttle)),
            (QColor(220, 60, 50), lambda s: float(s.brake)),
        ):
            p.setPen(QPen(col, 2))
            prev = None
            for s in rows:
                x = px(s)
                y = pedal_top + pedal_h * (1.0 - max(0.0, min(1.0, f(s))))
                if prev is not None and abs(x - prev[0]) <= 160:  # Sprung ueber Start/Ziel: unterbrechen
                    p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
                prev = (x, y)
        # Lenkung zentriert
        p.setPen(QPen(QColor(235, 185, 60), 2))
        prev = None
        for s in rows:
            x = px(s)
            y = steer_mid - max(-1.0, min(1.0, float(s.steering))) * steer_amp
            if prev is not None and abs(x - prev[0]) <= 160:
                p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
            prev = (x, y)
        # 0.2.26/0.2.27: gelber Positions-Streifen - automatisch am Ende, oder per Maus gezogen
        if self.cursor_dist is not None:
            cd = max(0.0, min(float(self.cursor_dist), dmax))
        else:
            cd = float(getattr(rows[-1], "lap_dist_m", 0.0) or 0.0)
        cur = left + (cd / dmax) * plot_w
        p.setPen(QPen(QColor(235, 185, 60), 2))
        p.drawLine(QPointF(cur, 20), QPointF(cur, h - 2))


class TrackMapWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.samples: List[Sample] = []
        self.reference_samples: List[Sample] = []
        self.compare_samples: List[Sample] = []
        self.segment_deltas: List[SegmentDelta] = []
        self.problem_zones = []
        self.heatmap_mode = False
        self.sector_bounds: List[float] = []  # 0.2.9: offizielle Sektorgrenzen (m), leer = unbekannt
        self.heat_metric = "delta"  # 0.4.8.8/0.4.8.9: "delta" | "pedal" | "line"
        self._line_idx = []        # 0.4.8.9: [(dist, x, z, path_lateral)] der Referenz
        self._path_lat_ok = False  # mPathLateral/mTrackEdge liefern Daten?
        self.setMinimumHeight(260)

    def set_heat_metric(self, metric):
        self.heat_metric = metric if metric in ("pedal", "line", "gear") else "delta"
        self.update()

    # ---- 0.4.8.9: Linienabweichung -------------------------------------
    def _build_line_index(self):
        idx = []
        for s in self.reference_samples:
            if abs(s.pos_x) > 0.001 or abs(s.pos_z) > 0.001:
                idx.append((float(s.lap_dist_m), float(s.pos_x), float(s.pos_z),
                            float(getattr(s, "path_lateral_m", 0.0) or 0.0)))
        idx.sort(key=lambda t: t[0])
        self._line_idx = idx
        self._path_lat_ok = any(abs(t[3]) > 1e-6 for t in idx) and any(
            abs(float(getattr(s, "path_lateral_m", 0.0) or 0.0)) > 1e-6 for s in self.compare_samples)

    def _lateral_dev(self, s):
        """Seitliche Abweichung dieser Probe zur Referenzlinie in Metern (signiert).
        Nutzt mPathLateral wenn der Kanal Daten liefert, sonst rein geometrisch
        (senkrechter Abstand zur Referenz-Spur). None wenn nicht bestimmbar."""
        idx = self._line_idx
        if len(idx) < 2:
            return None
        d = float(s.lap_dist_m)
        lo, hi = 0, len(idx) - 1
        if d <= idx[0][0] or d >= idx[-1][0]:
            return None
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if idx[mid][0] <= d:
                lo = mid
            else:
                hi = mid
        d0, x0, z0, pl0 = idx[lo]
        d1, x1, z1, pl1 = idx[hi]
        span = (d1 - d0) or 1.0
        if span > 60.0:
            return None
        t = (d - d0) / span
        if self._path_lat_ok:
            ref_pl = pl0 + (pl1 - pl0) * t
            return float(getattr(s, "path_lateral_m", 0.0) or 0.0) - ref_pl
        px = x0 + (x1 - x0) * t
        pz = z0 + (z1 - z0) * t
        hx, hz = (x1 - x0), (z1 - z0)
        ln = (hx * hx + hz * hz) ** 0.5
        if ln < 1e-6:
            return None
        nx, nz = hz / ln, -hx / ln
        return (float(s.pos_x) - px) * nx + (float(s.pos_z) - pz) * nz

    def _edge_margin_min(self):
        """Kleinster Restabstand zum Streckenrand in der Vergleichsrunde (Meter)."""
        if not self._path_lat_ok:
            return None
        best = None
        for s in self.compare_samples:
            edge = abs(float(getattr(s, "track_edge_m", 0.0) or 0.0))
            if edge < 0.5 or float(s.speed_kmh) < 5.0:
                continue
            m = edge - abs(float(getattr(s, "path_lateral_m", 0.0) or 0.0))
            if best is None or m < best:
                best = m
        return best

    def set_samples(self, samples: List[Sample]):
        self.samples = list(samples)
        self.heatmap_mode = False
        self.update()

    def set_heatmap(self, all_samples: List[Sample], reference_samples: List[Sample], compare_samples: List[Sample], segment_deltas: List[SegmentDelta], problem_zones):
        self.samples = list(all_samples)
        self.reference_samples = list(reference_samples)
        self.compare_samples = list(compare_samples)
        self.segment_deltas = list(segment_deltas)
        self.problem_zones = list(problem_zones)
        self.heatmap_mode = True
        self._build_line_index()  # 0.4.8.9
        self.update()

    def set_sector_info(self, bounds):
        """0.2.9: offizielle Sektorgrenzen (Meter) fuer Grenzmarken + Labels auf der Map."""
        b = [float(x) for x in (bounds or []) if float(x) > 0.0]
        self.sector_bounds = b[:2] if len(b) >= 2 else []
        self.update()

    def _sector_label_for_m(self, m: float) -> str:
        """0.2.9: S1/S2/S3 fuer eine Meter-Position anhand der offiziellen Grenzen."""
        if len(self.sector_bounds) >= 2:
            if m < self.sector_bounds[0]:
                return "S1"
            if m < self.sector_bounds[1]:
                return "S2"
            return "S3"
        return ""

    def _draw_sector_marks(self, painter, map_pt):
        """0.2.9: offizielle Sektorgrenzen als weisse X-Marken mit S1|S2-Label."""
        if len(self.sector_bounds) < 2:
            return
        pool = [s for s in (self.compare_samples or self.reference_samples or self.samples)
                if abs(s.pos_x) > 0.001 or abs(s.pos_z) > 0.001]
        if not pool:
            return
        for i, b in enumerate(self.sector_bounds[:2]):
            near = min(pool, key=lambda s: abs(s.lap_dist_m - b))
            if abs(near.lap_dist_m - b) > 60.0:
                continue
            pt = map_pt(near.pos_x, near.pos_z)
            painter.setPen(QPen(QColor(255, 255, 255, 225), 2))
            painter.drawLine(QPointF(pt.x() - 8, pt.y() - 8), QPointF(pt.x() + 8, pt.y() + 8))
            painter.drawLine(QPointF(pt.x() - 8, pt.y() + 8), QPointF(pt.x() + 8, pt.y() - 8))
            lbl = f"S{i + 1}|S{i + 2}"
            r = QRectF(pt.x() + 10, pt.y() - 32, 62, 18)
            painter.setBrush(QBrush(QColor(10, 10, 10, 175)))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawRoundedRect(r, 4, 4)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft, lbl)

    def _all_position_rows(self):
        # 0.2.0: Ergebnis cachen - paintEvent lief bisher bei jedem Repaint ueber alle Samples.
        key = (id(self.samples), len(self.samples), id(self.reference_samples), len(self.reference_samples),
               id(self.compare_samples), len(self.compare_samples))
        if getattr(self, "_rows_cache_key", None) == key:
            return self._rows_cache
        rows = []
        for src in (self.samples, self.reference_samples, self.compare_samples):
            rows.extend([s for s in src if abs(s.pos_x) > 0.001 or abs(s.pos_z) > 0.001])
        self._rows_cache_key = key
        self._rows_cache = rows
        return rows

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(24, 24, 24))
        painter.setPen(QPen(QColor(90, 90, 90), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        rows = self._all_position_rows()
        if len(rows) < 2:
            painter.setPen(QColor(210, 210, 210))
            painter.drawText(self.rect(), Qt.AlignCenter, "Trackmap: Recording starten und fahren")
            return

        xs = [s.pos_x for s in rows]; zs = [s.pos_z for s in rows]
        minx, maxx = min(xs), max(xs); minz, maxz = min(zs), max(zs)
        dx = max(maxx - minx, 1.0); dz = max(maxz - minz, 1.0)
        margin = 22
        w = max(self.width() - 2 * margin, 1); h = max(self.height() - 2 * margin, 1)
        scale = min(w / dx, h / dz)
        cx = (minx + maxx) / 2; cz = (minz + maxz) / 2

        def map_pt(x, z):
            px = self.width() / 2 + (x - cx) * scale
            py = self.height() / 2 - (z - cz) * scale
            return QPointF(px, py)

        def draw_path(path: List[Sample], pen_func, min_speed_for_line=1.0):
            pts = [s for s in path if s.speed_kmh >= min_speed_for_line and (abs(s.pos_x) > 0.001 or abs(s.pos_z) > 0.001)]
            if len(pts) < 2:
                return
            pts.sort(key=lambda s: (s.lap_dist_m, s.timestamp))
            for i in range(1, len(pts)):
                s0, s1 = pts[i - 1], pts[i]
                # avoid drawing a long line over start/finish wrap or bad distance jump
                if abs(s1.lap_dist_m - s0.lap_dist_m) > 160:
                    continue
                painter.setPen(pen_func(s1))
                painter.drawLine(map_pt(s0.pos_x, s0.pos_z), map_pt(s1.pos_x, s1.pos_z))

        if self.heatmap_mode and self.heat_metric == "gear" and (self.compare_samples or self.reference_samples):
            base = self.compare_samples or self.reference_samples
            gear_cols = {1: QColor(235, 70, 55), 2: QColor(245, 150, 55), 3: QColor(235, 195, 70),
                         4: QColor(140, 210, 90), 5: QColor(70, 190, 140), 6: QColor(70, 170, 235),
                         7: QColor(140, 130, 240), 8: QColor(210, 110, 235)}
            maxrpm = max([float(getattr(x, "max_rpm", 0.0) or 0.0) for x in base] + [0.0])
            if maxrpm < 1000:
                maxrpm = max([float(getattr(x, "rpm", 0.0) or 0.0) for x in base] + [1.0])

            def gear_pen(s: Sample):
                g = int(getattr(s, "gear", 0) or 0)
                col = gear_cols.get(g, QColor(140, 140, 140))
                frac = min(max(float(getattr(s, "rpm", 0.0) or 0.0) / maxrpm, 0.0), 1.0)
                return QPen(col, 2 + int(4 * frac))

            draw_path(base, gear_pen, 3.0)
            painter.setPen(QColor(230, 230, 230))
            painter.drawText(QRectF(8, 8, self.width() - 16, 44), Qt.AlignLeft,
                             "Gang & Drehzahl: Farbe = Gang (1 rot → 8 violett) · Liniendicke = Drehzahl")
            gx = 10
            for g in range(1, 9):
                painter.setPen(QPen(gear_cols[g], 4))
                painter.drawLine(QPointF(gx, self.height() - 14), QPointF(gx + 16, self.height() - 14))
                painter.setPen(QColor(220, 220, 220))
                painter.drawText(QRectF(gx + 18, self.height() - 22, 12, 16), Qt.AlignLeft, str(g))
                gx += 36
            return

        if self.heatmap_mode and self.heat_metric == "line" and self.compare_samples and self.reference_samples:
            draw_path(self.reference_samples, lambda s: QPen(QColor(120, 120, 120), 2), 5.0)

            def line_pen(s: Sample):
                dv = self._lateral_dev(s)
                if dv is None:
                    return QPen(QColor(150, 150, 150), 2)
                a = abs(dv)
                if a < 0.3:
                    return QPen(QColor(120, 200, 140), 2)
                if a < 0.8:
                    return QPen(QColor(235, 195, 70), 3)
                if a < 1.5:
                    return QPen(QColor(245, 150, 55), 4)
                return QPen(QColor(235, 70, 55), 5)

            draw_path(self.compare_samples, line_pen, 5.0)

            # groesste Abweichungen markieren (max. 3, je 50-m-Bucket)
            buckets = {}
            for s in self.compare_samples:
                if s.speed_kmh < 5.0:
                    continue
                dv = self._lateral_dev(s)
                if dv is None:
                    continue
                key = int(s.lap_dist_m // 50) * 50
                cur = buckets.get(key)
                if cur is None or abs(dv) > abs(cur[0]):
                    buckets[key] = (dv, s)
            top = sorted(buckets.values(), key=lambda t: -abs(t[0]))[:3]
            for rank, (dv, s) in enumerate(top, 1):
                if abs(dv) < 0.4:
                    continue
                pt = map_pt(s.pos_x, s.pos_z)
                painter.setBrush(QBrush(QColor(245, 150, 55, 230)))
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.drawEllipse(pt, 15, 15)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(QRectF(pt.x() - 12, pt.y() - 12, 24, 24), Qt.AlignCenter, str(rank))
                side = "aussen" if dv > 0 else "innen"
                label = f"{abs(dv):.1f} m {side}"
                lr = QRectF(pt.x() + 17, pt.y() - 14, 118, 26)
                painter.setBrush(QBrush(QColor(10, 10, 10, 185)))
                painter.setPen(QPen(QColor(245, 150, 55), 1))
                painter.drawRoundedRect(lr, 5, 5)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(lr.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, label)

            src_txt = "Quelle: mPathLateral" if self._path_lat_ok else "Quelle: Positionen (mPathLateral leer)"
            margin = self._edge_margin_min()
            margin_txt = f" · engster Rand-Abstand {margin:.2f} m" if margin is not None else ""
            painter.setPen(QColor(230, 230, 230))
            painter.drawText(QRectF(8, 8, self.width() - 16, 44), Qt.AlignLeft,
                             "Linienabweichung zur Referenz: grün <0,3 m · gelb <0,8 · orange <1,5 · rot darüber | "
                             + src_txt + margin_txt)
            return

        if self.heatmap_mode and self.heat_metric == "pedal" and (self.compare_samples or self.reference_samples):
            base = self.compare_samples or self.reference_samples
            if self.reference_samples and base is not self.reference_samples:
                draw_path(self.reference_samples, lambda s: QPen(QColor(85, 85, 85), 2), 5.0)
            def pedal_pen(s: Sample):
                if s.brake > 0.05:
                    return QPen(QColor(235, 70, 55), 2 + int(3 * min(s.brake, 1.0)))
                if s.throttle > 0.05:
                    return QPen(QColor(70, 190, 90), 2 + int(2 * min(s.throttle, 1.0)))
                return QPen(QColor(235, 185, 60), 2)
