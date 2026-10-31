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
    QCheckBox, QSpinBox, QProgressDialog, QSizeGrip, QDialog, QDialogButtonBox
)

import ctypes
from tts import SpeechEngine  # 0.4.7.2: Offline-Sprachausgabe
import updater  # 0.4.7.5: Update-Pruefung ueber GitHub Releases
import ai_providers  # 0.2.1: optionale KI-Anbieter fuer den Live-Coach
from raceroom_sm import R3EReader  # RaceRoom Shared Memory ($R3E)
from corner_db import CORNER_SECTIONS  # 0.2.38: echte Kurvennamen (Basis: SealHUD, MIT)
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QIcon, QPixmap, QDesktopServices, QShortcut, QKeySequence, QFont, QFontMetricsF, QPainterPath

APP_VERSION = "0.2.43 Beta"
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
HOTKEY_CONFIG_PATH = EXPORT_DIR / "hotkeys.json"  # 0.2.5: frei belegbare Hotkeys (Stream Deck)
UI_LAYOUT_PATH = EXPORT_DIR / "ui_layout.json"  # 0.2.10: Einfache Ansicht vs. Experte
ANALYSIS_CONFIG_PATH = EXPORT_DIR / "analysis_config.json"  # 0.2.31: Auswertungs-Optionen
FEEDBACK_DIR = EXPORT_DIR / "feedback"  # 0.2.33: Beta-Tester-Feedback (offline gespeicherte Dateien)

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
            draw_path(base, pedal_pen, 3.0)
            painter.setPen(QColor(230, 230, 230))
            painter.drawText(QRectF(8, 8, self.width() - 16, 44), Qt.AlignLeft,
                             "Pedal-Input: grün = Gas · rot = Bremse · gelb = Segeln | grau = Referenz")
            return

        if self.heatmap_mode and self.reference_samples and self.compare_samples and self.segment_deltas:
            delta_by_bucket = {d.start_m: d for d in self.segment_deltas}
            draw_path(self.reference_samples, lambda s: QPen(QColor(110, 110, 110), 2), 5.0)

            def heat_pen(s: Sample):
                key = int(s.lap_dist_m // 50) * 50
                d = delta_by_bucket.get(key)
                if d is None:
                    return QPen(QColor(150, 150, 150), 2)
                if d.delta_s >= 0.14:
                    return QPen(QColor(235, 70, 55), 5)
                if d.delta_s >= 0.06:
                    return QPen(QColor(245, 170, 60), 4)
                if d.delta_s <= -0.10:
                    return QPen(QColor(70, 190, 90), 4)
                return QPen(QColor(190, 190, 190), 2)

            draw_path(self.compare_samples, heat_pen, 5.0)

            def draw_zone_segment(start_m: int, end_m: int, idx: int, loss: float):
                # Draw the complete problem zone as a thick highlighted track section.
                pts = [s for s in self.compare_samples
                       if s.speed_kmh >= 5.0 and start_m <= s.lap_dist_m <= end_m
                       and (abs(s.pos_x) > 0.001 or abs(s.pos_z) > 0.001)]
                pts.sort(key=lambda s: (s.lap_dist_m, s.timestamp))
                if len(pts) >= 2:
                    zone_color = QColor(255, 70, 55, 205) if loss >= 0.30 else QColor(245, 160, 55, 205)
                    painter.setPen(QPen(zone_color, 10, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    for i in range(1, len(pts)):
                        if abs(pts[i].lap_dist_m - pts[i - 1].lap_dist_m) <= 120:
                            painter.drawLine(map_pt(pts[i - 1].pos_x, pts[i - 1].pos_z), map_pt(pts[i].pos_x, pts[i].pos_z))

                mid = (start_m + end_m) / 2
                nearest = min(self.compare_samples, key=lambda s: abs(s.lap_dist_m - mid), default=None)
                if nearest is None:
                    return
                pt = map_pt(nearest.pos_x, nearest.pos_z)
                # Large numbered marker with a small text label.
                painter.setBrush(QBrush(QColor(255, 70, 55, 230)))
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.drawEllipse(pt, 18, 18)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(QRectF(pt.x() - 12, pt.y() - 13, 24, 26), Qt.AlignCenter, str(idx))
                sec = self._sector_label_for_m(start_m)  # 0.2.9: offizieller Sektor der Zone
                label = f"Zone {idx}: {start_m}-{end_m} m" + (f" ({sec})" if sec else "")
                label_rect = QRectF(pt.x() + 20, pt.y() - 16, 135, 30)
                painter.setBrush(QBrush(QColor(10, 10, 10, 185)))
                painter.setPen(QPen(QColor(255, 90, 80), 1))
                painter.drawRoundedRect(label_rect, 5, 5)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(label_rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, label)

            # Mark grouped coach zones clearly as thick colored track sections.
            for idx, zone in enumerate(self.problem_zones[:5], 1):
                start, end, loss = zone[0], zone[1], zone[2]
                draw_zone_segment(start, end, idx, loss)

            painter.setPen(QColor(230, 230, 230))
            painter.drawText(QRectF(8, 8, self.width() - 16, 44), Qt.AlignLeft,
                             "Heatmap: dicke rote Zonen + Nummern = Coach-Fokus | Grau=Referenz | Grün=besser | X=Sektorgrenze")
            # 0.2.26: aktuelle Position auch im Heatmap-Modus als gelber Punkt
            try:
                cur = self.compare_samples or self.reference_samples or self.samples
                if cur:
                    s = cur[-1]
                    if abs(float(s.pos_x)) > 0.001 or abs(float(s.pos_z)) > 0.001:
                        q = map_pt(float(s.pos_x), float(s.pos_z))
                        painter.setPen(QPen(QColor(235, 185, 60), 2))
                        painter.drawEllipse(q, 7, 7)
                        painter.setPen(QPen(QColor(16, 16, 16), 2))
                        painter.drawEllipse(q, 3, 3)
            except Exception:
                pass
            self._draw_sector_marks(painter, map_pt)
        else:
            pts = self.samples
            max_speed = max([s.speed_kmh for s in pts] + [1.0])
            def live_pen(s: Sample):
                if s.brake > 0.05:
                    return QPen(QColor(230, 100, 80), 3)
                if s.throttle > 0.8:
                    return QPen(QColor(90, 180, 110), 2)
                shade = int(120 + 100 * min(max(s.speed_kmh / max_speed, 0), 1))
                return QPen(QColor(shade, shade, shade), 2)
            draw_path(pts, live_pen, 0.0)
            last = pts[-1]
            painter.setBrush(QBrush(QColor(255, 230, 80)))
            painter.setPen(QPen(QColor(0, 0, 0), 2))
            lp = map_pt(last.pos_x, last.pos_z)
            painter.drawEllipse(lp, 7, 7)  # 0.2.26: groesser, damit die Position klar erkennbar ist
            painter.setPen(QColor(220, 220, 220))
            painter.drawText(QRectF(8, 8, self.width() - 16, 20), Qt.AlignLeft, f"Samples: {len(self.samples)} | Speed max: {max_speed:.1f} km/h | Rot=Bremse | Grün=Gas | X=Sektorgrenze")
            self._draw_sector_marks(painter, map_pt)


def _load_overlay_sizes():
    """0.4.9.8: gemerkte Overlay-Groessen (pro Klasse) laden."""
    try:
        import json
        with open(OVERLAY_SIZES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


_OVERLAY_SIZES = None


def _remember_overlay_size(widget):
    global _OVERLAY_SIZES
    # 0.4.9.8: Erst speichern, wenn die gemerkte Groesse angewendet wurde - sonst
    # ueberschreibt das resizeEvent beim Anzeigen die Datei mit der Standardgroesse.
    if not getattr(widget, "_size_restored", False):
        return
    if _OVERLAY_SIZES is None:
        _OVERLAY_SIZES = _load_overlay_sizes()
    try:
        _OVERLAY_SIZES[type(widget).__name__] = [int(widget.width()), int(widget.height())]
        # 0.2.42: Skalierung + Deckkraft pro Overlay mit merken
        _OVERLAY_SIZES[type(widget).__name__ + ":scale"] = round(float(getattr(widget, "ov_scale", 1.0)), 3)
        _OVERLAY_SIZES[type(widget).__name__ + ":opacity"] = round(float(getattr(widget, "ov_opacity", 1.0)), 3)
        import json
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OVERLAY_SIZES_PATH, "w", encoding="utf-8") as f:
            json.dump(_OVERLAY_SIZES, f, indent=2)
    except Exception:
        pass


def _remember_overlay_state(widget):
    """0.2.42: Deckkraft/Skalierung sofort speichern (auch ohne resize)."""
    global _OVERLAY_SIZES
    try:
        if _OVERLAY_SIZES is None:
            _OVERLAY_SIZES = _load_overlay_sizes()
        _OVERLAY_SIZES[type(widget).__name__ + ":scale"] = round(float(getattr(widget, "ov_scale", 1.0)), 3)
        _OVERLAY_SIZES[type(widget).__name__ + ":opacity"] = round(float(getattr(widget, "ov_opacity", 1.0)), 3)
        import json
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OVERLAY_SIZES_PATH, "w", encoding="utf-8") as f:
            json.dump(_OVERLAY_SIZES, f, indent=2)
    except Exception:
        pass


def _restore_overlay_size(widget):
    global _OVERLAY_SIZES
    if getattr(widget, "_size_restored", False):
        return
    widget._size_restored = True
    if _OVERLAY_SIZES is None:
        _OVERLAY_SIZES = _load_overlay_sizes()
    try:
        wh = _OVERLAY_SIZES.get(type(widget).__name__)
        if wh and len(wh) == 2:
            w = max(int(wh[0]), widget.minimumWidth())
            h = max(int(wh[1]), widget.minimumHeight())
            widget.resize(w, h)
        # 0.2.42: gemerkte Skalierung/Deckkraft wiederherstellen (Reihenfolge:
        # erst Groesse, dann ov_scale - die gemerkte Groesse enthaelt bereits den Faktor)
        try:
            sc = _OVERLAY_SIZES.get(type(widget).__name__ + ":scale")
            sc = max(0.5, min(2.5, float(sc))) if sc else 1.0
        except Exception:
            sc = 1.0
        widget.ov_scale = sc
        if sc != 1.0:
            widget._ov_base_size = (max(10.0, widget.width() / sc), max(10.0, widget.height() / sc))
        op = _OVERLAY_SIZES.get(type(widget).__name__ + ":opacity")
        try:
            widget.ov_opacity = max(0.15, min(1.0, float(op))) if op else 1.0
        except Exception:
            widget.ov_opacity = 1.0
        try:
            widget.setWindowOpacity(widget.ov_opacity)
        except Exception:
            pass
    except Exception:
        pass



_FIT_CACHE = {}


def _fit_font(text, max_w, max_h, start_pt, bold=True, family="Segoe UI", min_pt=7.0):
    """0.2.0: groesste Schrift <= start_pt, die in max_w x max_h passt. Gecacht nach
    (Breite, Hoehe, Start, Textlaenge), damit Overlays mit 20 Hz nicht jedes Mal suchen."""
    key = (int(max_w), int(max_h), float(start_pt), len(text), bold, family)
    f = _FIT_CACHE.get(key)
    if f is not None:
        return QFont(f)
    f = QFont(family); f.setBold(bold)
    pt = float(start_pt)
    while pt > min_pt:
        f.setPointSizeF(pt)
        fm = QFontMetricsF(f)
        if fm.horizontalAdvance(text) <= max_w and fm.height() <= max_h:
            break
        pt -= 0.5
    f.setPointSizeF(max(min_pt, pt))
    if len(_FIT_CACHE) > 256:
        _FIT_CACHE.clear()
    _FIT_CACHE[key] = QFont(f)
    return f


class OverlayStyleMixin:
    """0.4.9.1: gemeinsames Erscheinungsbild aller Overlays.
    Drei Modi: 'transparent' (durchscheinend wie bisher das Reifen-Overlay),
    'dark' und 'light' (deckend, passend zum App-Theme). Die Fensterflagge
    WA_TranslucentBackground bleibt immer gesetzt - deckend wird ueber den
    Alpha-Wert gemalt, damit das Fenster nie neu erzeugt werden muss.
    Semantische Farben (gruen/gelb/rot) bleiben in allen Modi gleich."""

    def apply_overlay_style(self, mode):
        self.overlay_style = mode if mode in ("transparent", "dark", "light") else "transparent"
        try:
            self._restyle()
        except Exception:
            pass
        # 0.4.9.6: an Kind-Widgets weiterreichen (z.B. die Reifengrafiken)
        try:
            for child in self.findChildren(QWidget):
                if child is not self and hasattr(child, "apply_overlay_style"):
                    child.overlay_style = self.overlay_style
                    try:
                        child._restyle()
                    except Exception:
                        pass
                    child.update()
        except Exception:
            pass
        self.update()

    def _restyle(self):
        """Von QSS-basierten Overlays ueberschrieben."""
        return None

    def _st(self):
        return getattr(self, "overlay_style", "transparent")

    def _bg(self):
        s = self._st()
        if s == "light":
            return QColor(250, 250, 252, 255)
        if s == "dark":
            return QColor(12, 12, 14, 255)
        return QColor(12, 12, 14, 222)

    def _panel(self):
        s = self._st()
        if s == "light":
            return QColor(255, 255, 255, 255)
        if s == "dark":
            return QColor(24, 24, 28, 255)
        return QColor(24, 24, 28, 225)

    def _fg(self):
        return QColor("#16161a") if self._st() == "light" else QColor("#ffffff")

    def _muted(self):
        return QColor("#666671") if self._st() == "light" else QColor("#b6b8c0")

    def _border(self):
        return QColor("#d4d4da") if self._st() == "light" else QColor("#2c2c33")

    def _trackcol(self):
        return QColor(226, 226, 231) if self._st() == "light" else QColor(38, 38, 44)

    def _paint_frame(self, p, w, h, accent=True):
        """0.2.3: Rahmen im Stil des RaceRoom-HUDs: keine Kontur, kein Akzentbalken, nur eine
        dezente dunkle Flaeche. 'transparent' (Standard) = weicher Verlauf links->rechts, damit
        die Strecke durchscheint; 'dark'/'light' = deckend mit feiner Kontur. (accent bleibt
        aus Kompatibilitaet in der Signatur, wird nicht mehr gezeichnet.)"""
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        st = self._st()
        if st == "transparent":
            # 0.2.43: Nutzerwunsch - im transparenten Design GAR KEIN Hintergrund
            # (weder Verlauf noch Flaeche). Text bleibt ueber dem Spiel lesbar,
            # die Strecke scheint voll durch. 'dark'/'light' zeichnen wie bisher.
            p.setPen(Qt.NoPen); p.setBrush(Qt.NoBrush)
        else:
            p.setPen(QPen(self._border(), 1)); p.setBrush(self._bg())
            p.drawRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0))
        p.restore()

    def _draw_title(self, p, rect, text):
        """0.2.3: Titel wie im Spiel: weiss, fett, Versalien, leicht gesperrt."""
        p.save()
        f = QFont(); f.setPointSizeF(9.5); f.setBold(True); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f); p.setPen(self._fg())
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, str(text).upper())
        p.restore()

    def _kv_row(self, p, w, y, key, val, color=None, left=10, right=12, h=16):
        """0.2.3: Zeile wie im Boxenstopp-Menue des Spiels: Beschriftung links (Versalien, grau),
        Wert rechts (weiss, fett)."""
        p.save()
        fk = QFont(); fk.setPointSizeF(8); fk.setBold(True); fk.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
        p.setFont(fk); p.setPen(self._muted())
        p.drawText(QRectF(left, y, w - left - right, h), Qt.AlignVCenter | Qt.AlignLeft, str(key).upper())
        fx = QFont(); fx.setPointSizeF(10); fx.setBold(True); p.setFont(fx)
        p.setPen(color or self._fg())
        p.drawText(QRectF(left, y, w - left - right, h), Qt.AlignVCenter | Qt.AlignRight, str(val))
        p.restore()

    def _faint(self, alpha=50):
        """0.4.9.6: dezente Linien - im hellen Design dunkel statt weiss."""
        c = self._fg()
        return QColor(c.red(), c.green(), c.blue(), alpha)

    # ---- 0.2.42: Skalierung + Deckkraft fuer ALLE Overlays (Vorbild: Reifen-Overlay) ----
    def set_ui_scale(self, scale):
        new = max(0.5, min(2.5, float(scale) or 1.0))
        self.ov_scale = new
        if not getattr(self, "_ov_base_size", None):
            self._ov_base_size = (self.width(), self.height())
        bw, bh = self._ov_base_size
        self.resize(int(bw * new), int(bh * new))
        try:
            _remember_overlay_state(self)
        except Exception:
            pass
        self.update()

    def set_ui_opacity(self, op):
        self.ov_opacity = max(0.15, min(1.0, float(op)))
        try:
            self.setWindowOpacity(self.ov_opacity)
            _remember_overlay_state(self)
        except Exception:
            pass

    def _begin_paint(self):
        """QPainter mit Skalierung: Der Fensterinhalt (inkl. Schrift) waechst
        mit dem Faktor ov_scale mit, statt nur den Rahmen zu vergroessern."""
        p = QPainter(self)
        s = float(getattr(self, "ov_scale", 1.0) or 1.0)
        if abs(s - 1.0) > 1e-6:
            p.scale(s, s)
        return p

    def _lw(self):
        return self.width() / max(0.05, float(getattr(self, "ov_scale", 1.0) or 1.0))

    def _lh(self):
        return self.height() / max(0.05, float(getattr(self, "ov_scale", 1.0) or 1.0))

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d != 0:
            self.set_ui_scale(float(getattr(self, "ov_scale", 1.0) or 1.0) + (0.1 if d > 0 else -0.1))
            event.accept()

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        sm = menu.addMenu("Skalierung")
        for label, val in [("75 %", 0.75), ("100 %", 1.0), ("125 %", 1.25), ("150 %", 1.5), ("175 %", 1.75), ("200 %", 2.0)]:
            sm.addAction(label, lambda v=val: self.set_ui_scale(v))
        om = menu.addMenu("Deckkraft")
        for label, val in [("20 %", 0.2), ("40 %", 0.4), ("60 %", 0.6), ("80 %", 0.8), ("100 %", 1.0)]:
            om.addAction(label, lambda v=val: self.set_ui_opacity(v))
        menu.exec(event.globalPos())

    # ---- 0.4.9.8: Groesse per Ziehen veraendern -------------------------
    def _ensure_grip(self):
        """Griff unten rechts. QSizeGrip kann auch rahmenlose Fenster skalieren."""
        if getattr(self, "_size_grip", None) is not None:
            return
        try:
            g = QSizeGrip(self)
            g.setFixedSize(18, 18)
            g.setToolTip("Ziehen: Gr\u00f6\u00dfe \u00e4ndern")
            g.setStyleSheet("background: transparent;")
            self._size_grip = g
            g.show(); g.raise_()
        except Exception:
            self._size_grip = None

    def _place_grip(self):
        g = getattr(self, "_size_grip", None)
        if g is not None:
            g.move(self.width() - g.width() - 2, self.height() - g.height() - 2)
            g.raise_()

    def showEvent(self, ev):
        self._ensure_grip()
        # 0.4.9.8: Groesse erst nach dem Show-Durchlauf setzen - Qt legt die
        # Fenstergeometrie sonst danach fest und ueberschreibt das resize().
        QTimer.singleShot(0, lambda: (_restore_overlay_size(self), self._place_grip()))
        self._place_grip()
        try:
            super().showEvent(ev)
        except Exception:
            pass

    def resizeEvent(self, ev):
        self._place_grip()
        _remember_overlay_size(self)
        try:
            super().resizeEvent(ev)
        except Exception:
            pass

    def _drag_start(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def _drag_move(self, ev):
        if getattr(self, "_drag", None) is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag)
            ev.accept()


class PitOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.9.1: Boxenstopp-Status. Oeffnet automatisch beim Einfahren in die
    Boxengasse und schliesst sich beim Verlassen wieder (nur wenn es automatisch
    geoeffnet wurde - manuell geoeffnet bleibt es stehen)."""

    STATES = {0: ("keine Anforderung", "#8a97a8"), 1: ("Stopp angefordert", "#e3b341"),
              2: ("Einfahrt Boxengasse", "#58a6ff"), 3: ("steht in der Box", "#3fb950"),
              4: ("Ausfahrt Boxengasse", "#58a6ff")}

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Pit Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(250, 182)
        self.setMinimumSize(200, 160)
        self.auto_opened = False
        self._d = None
        self._drag = None

    def update_from_main(self, main):
        self._d = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        self.update()

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
        self._draw_title(p, QRectF(10, 6, w - 20, 16), "BOXENSTOPP")
        s = self._d
        if s is None:
            p.setPen(self._muted()); p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "warte auf Telemetrie")
            p.end(); return
        state = int(getattr(s, "pit_state", 0) or 0)
        label, col = self.STATES.get(state, ("unbekannt", "#8a97a8"))
        in_pits = bool(getattr(s, "in_pits", False))
        limiter = bool(getattr(s, "speed_limiter", False))
        fv = QFont(); fv.setPointSize(14); fv.setBold(True); p.setFont(fv); p.setPen(QColor(col))
        p.drawText(QRectF(10, 24, w - 20, 24), Qt.AlignLeft, label)

        def row(y, key, val, color=None):
            self._kv_row(p, w, y, key, val, color)

        row(54, "in der Boxengasse", "ja" if in_pits else "nein",
            QColor("#3fb950") if in_pits else self._fg())
        row(74, "Begrenzer", "AN" if limiter else "AUS",
            QColor("#3fb950") if limiter else (QColor("#f85149") if in_pits else self._muted()))
        row(94, "Tempo", f"{float(getattr(s, 'speed_kmh', 0.0) or 0.0):.0f} km/h")
        row(114, "Stopps bisher", str(int(getattr(s, "num_pitstops", 0) or 0)))
        tot = float(getattr(s, "pit_total_s", -1.0))
        ela = float(getattr(s, "pit_elapsed_s", -1.0))
        if state == 3 and tot > 0.0 and ela >= 0.0:
            row(134, "Standzeit", f"{ela:.0f} / {tot:.0f} s", QColor("#3fb950"))
        else:
            row(134, "Sprit", f"{float(getattr(s, 'fuel_l', 0.0) or 0.0):.1f} l")
        win = int(getattr(s, "pit_window_status", -1))
        win_txt = {0: "aus", 1: "geschlossen", 2: "OFFEN", 3: "Stopp l\u00e4uft", 4: "erledigt"}.get(win)
        if win_txt:
            row(154, "Stoppfenster", win_txt, QColor("#3fb950") if win == 2 else None)
        p.end()


class DeltaOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.9.1: Abstand nach vorn und hinten in Sekunden, dazu die daraus
    geschaetzte Distanz in Metern (Zeit x eigenes Tempo), plus Rueckstand auf
    den Fuehrenden. Runden-Rueckstaende werden getrennt ausgewiesen."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Delta Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(268, 150)
        self.setMinimumSize(240, 126)
        self._d = None
        self._drag = None

    def update_from_main(self, main):
        self._d = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        self.update()

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
        self._draw_title(p, QRectF(12, 6, w - 20, 16), "ABSTAND & DISTANZ")
        s = self._d
        if s is None:
            p.setPen(self._muted()); p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "warte auf Telemetrie")
            p.end(); return
        spd = float(getattr(s, "speed_kmh", 0.0) or 0.0) / 3.6
        place = int(getattr(s, "place", 0) or 0)
        fv = QFont(); fv.setPointSize(13); fv.setBold(True); p.setFont(fv); p.setPen(self._fg())
        p.drawText(QRectF(10, 24, w - 20, 20), Qt.AlignLeft, f"P {place}" if place else "P \u2014")

        def gap_row(y, key, gap_s, laps, color):
            fl = QFont(); fl.setPointSizeF(8); fl.setBold(True); fl.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
            p.setFont(fl); p.setPen(self._muted())
            p.drawText(QRectF(12, y, 114, 18), Qt.AlignVCenter | Qt.AlignLeft, key.upper())
            fx = QFont(); fx.setPointSize(12); fx.setBold(True); p.setFont(fx); p.setPen(color)
            if laps and laps > 0:
                txt = f"+{laps} Rd"
            elif gap_s and gap_s > 0.001:
                txt = f"{gap_s:.2f} s"
            else:
                txt = "\u2014"
            p.drawText(QRectF(128, y, 66, 18), Qt.AlignVCenter | Qt.AlignLeft, txt)
            fm = QFont(); fm.setPointSize(9); p.setFont(fm); p.setPen(self._muted())
            dist = (gap_s * spd) if (gap_s and gap_s > 0.001 and not laps) else 0.0
            p.drawText(QRectF(196, y, w - 204, 18), Qt.AlignVCenter | Qt.AlignLeft,
                       f"{dist:.0f} m" if dist > 0.5 else "")

        gap_ahead = float(getattr(s, "gap_ahead_s", 0.0) or 0.0)
        gap_behind = float(getattr(s, "gap_behind_s", 0.0) or 0.0)
        gap_leader = float(getattr(s, "gap_leader_s", 0.0) or 0.0)
        gap_row(50, "nach vorn", gap_ahead, int(getattr(s, "laps_behind_next", 0) or 0), QColor("#f85149"))
        gap_row(76, "nach hinten", gap_behind, 0, QColor("#3fb950"))
        gap_row(102, "auf F\u00fchrenden", gap_leader, int(getattr(s, "laps_behind_leader", 0) or 0), QColor("#58a6ff"))
        fn = QFont(); fn.setPointSize(7); p.setFont(fn); p.setPen(self._muted())
        p.drawText(QRectF(0, h - 16, w, 12), Qt.AlignCenter, "Distanz = Abstand x eigenes Tempo")
        p.end()


class LapTimeOverlayWindow(OverlayStyleMixin, QWidget):
    """0.5.1.0: Rundenzeiten im neuen Design (Bild 1) - links ein Delta-Ring,
    rechts ein Streifen AKTUELL / DELTA / SESSION-BEST / PROGNOSE. Delta = Live-
    Delta zur Session-Bestrunde (gruen = schneller). Prognose = Bestzeit + Delta."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Rundenzeiten Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(440, 96)
        self.setMinimumSize(380, 80)
        self._d = None
        self._delta = 0.0
        self._clock_anchor_raw = None   # 0.5.9.26: fuer Echtzeit-Extrapolation, s.u.
        self._clock_anchor_ts = None
        self._drag = None
        self._self_timer = QTimer(self)  # eigener Repaint-Takt, laeuft nur bei sichtbarem Fenster
        self._self_timer.setInterval(50)  # 20 Hz: AKTUELL laeuft per time.monotonic() weich weiter
        self._self_timer.timeout.connect(self._self_tick)

    def _self_tick(self):  # 0.5.9.26
        if self.isVisible():
            self.update()  # paintEvent extrapoliert AKTUELL frisch per time.monotonic()

    def showEvent(self, ev):
        OverlayStyleMixin.showEvent(self, ev)
        self._self_timer.start()  # 0.2.0: Repaint-Takt nur solange das Fenster sichtbar ist

    def hideEvent(self, ev):
        self._self_timer.stop()
        try:
            super().hideEvent(ev)
        except Exception:
            pass

    def update_from_main(self, main):
        self._d = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        self._clock_anchor_raw = getattr(main, "_live_clock_anchor_raw", None)  # 0.5.9.26
        self._clock_anchor_ts = getattr(main, "_live_clock_anchor_ts", None)
        try:
            self._delta = float(getattr(main, "live_delta_s", 0.0) or 0.0)
        except Exception:
            self._delta = 0.0
        self.update()

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def paintEvent(self, _):
        # 0.2.0: neu im RaceRoom-Stil. Kein Delta-Ring mehr (teure Boegen bei 20 Hz),
        # stattdessen grosse Delta-Zahl, drei Zeitspalten und ein schmaler Delta-Balken.
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        s = self._d
        green = QColor("#3fb950"); red = QColor("#f85149")
        delta = self._delta
        dcol = green if delta <= 0 else red
        pad = 14
        bar_h = 6
        bar_y = h - bar_h - 9
        body_h = bar_y - 8

        if s is None:
            p.setPen(self._muted()); p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
            p.drawText(QRectF(pad, 0, w - 2 * pad, h), Qt.AlignVCenter | Qt.AlignLeft, "RUNDENZEITEN – warte auf Telemetrie")
            p.end(); return

        cur = (self._clock_anchor_raw + (time.monotonic() - self._clock_anchor_ts)) \
              if self._clock_anchor_raw is not None and self._clock_anchor_ts is not None \
              else float(getattr(s, "current_lap_time", 0.0) or 0.0)
        cur = max(0.0, cur)
        best = float(getattr(s, "best_lap_time", 0.0) or 0.0)
        last = float(getattr(s, "last_lap_time", 0.0) or 0.0)
        pred = (best + delta) if best > 0 else last

        lab_font = QFont("Segoe UI", 7, QFont.DemiBold)
        dw = min(140.0, w * 0.28)
        # Delta-Block links
        p.setFont(lab_font); p.setPen(self._muted())
        p.drawText(QRectF(pad, 8, dw, 13), Qt.AlignLeft | Qt.AlignVCenter, "DELTA")
        dtxt = f"{delta:+.2f}"
        p.setFont(_fit_font(dtxt, dw, body_h - 14, 26)); p.setPen(dcol)
        p.drawText(QRectF(pad, 22, dw, body_h - 14), Qt.AlignLeft | Qt.AlignVCenter, dtxt)
        # Trenner
        p.setPen(QPen(self._border(), 1)); p.drawLine(int(pad + dw + 4), 10, int(pad + dw + 4), int(bar_y - 4))
        # Zeitspalten
        x = pad + dw + 14
        cw = (w - x - pad) / 3.0
        cells = (
            ("AKTUELL", fmt_lap_time(cur) if cur > 0 else "--:--.---", self._fg()),
            ("BESTE", fmt_lap_time(best) if best > 0 else "--:--.---", self._fg()),
            ("PROGNOSE", fmt_lap_time(pred) if pred > 0 else "--:--.---", green if delta <= 0 else red),
        )
        vfont = _fit_font("8:88.888", cw - 6, body_h - 14, 16)
        for label, val, col in cells:
            p.setFont(lab_font); p.setPen(self._muted())
            p.drawText(QRectF(x, 8, cw, 13), Qt.AlignLeft | Qt.AlignVCenter, label)
            p.setFont(vfont); p.setPen(col)
            p.drawText(QRectF(x, 22, cw, body_h - 14), Qt.AlignLeft | Qt.AlignVCenter, val)
            x += cw
        # Delta-Balken (+-2 s): links = schneller (gruen), rechts = langsamer (rot)
        bx = pad; bw = w - 2 * pad
        p.setPen(Qt.NoPen); p.setBrush(self._trackcol()); p.drawRect(QRectF(bx, bar_y, bw, bar_h))
        frac = max(-1.0, min(1.0, delta / 2.0))
        mid = bx + bw / 2.0
        p.setBrush(dcol)
        if frac >= 0:
            p.drawRect(QRectF(mid, bar_y, frac * bw / 2.0, bar_h))
        else:
            p.drawRect(QRectF(mid + frac * bw / 2.0, bar_y, -frac * bw / 2.0, bar_h))
        p.setBrush(self._fg()); p.drawRect(QRectF(mid - 1, bar_y - 2, 2, bar_h + 4))
        p.end()

class FlagOverlayWindow(OverlayStyleMixin, QWidget):
    """0.5.1.0: Flaggen-Overlay im LED-Matrix-Stil (Bild 2). Quelle: mGamePhase,
    mYellowFlagState, mSectorFlag[eigener Sektor] und das fahrzeugeigene mFlag
    (6 = blau). Prioritaet: Ziel > Rot > Voll-Gelb > Blau > lokal Gelb > Weiss >
    Gruen. Selbst-diagnostizierend ohne Session."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Flaggen Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(150, 150)
        self.setMinimumSize(90, 90)
        self._flag = "none"; self._label = "\u2014"; self._drag = None

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        self._flag, self._label = self._decide(s)
        self.update()

    @staticmethod
    def _decide(s):
        if s is None:
            return "none", "\u2014"
        phase = int(getattr(s, "game_phase", 0) or 0)
        yfs = int(getattr(s, "yellow_flag_state", 0) or 0)
        pf = int(getattr(s, "player_flag", 0) or 0)
        # 0.5.9.28: sector_flag_0/1/2 (mSectorFlag) rausgenommen - bei Marcel per Live-Log
        # bestaetigt konstant 11 ueber eine komplette Session ohne jede Abweichung, obwohl
        # yellow_flag_state/game_phase/player_flag die ganze Zeit korrekt "kein Flag" zeigten.
        # Die alte "jeder Wert != 0 = GELB (LOKAL)"-Regel loeste dadurch DAUERHAFT falsch aus.
        # Ohne verlaessliche Doku, welches Bit wirklich "lokale Gelbflagge" bedeutet, ist das
        # Feld hier nicht mehr vertrauenswuerdig auswertbar -> Check entfernt statt geraten.
        if phase == 8:
            return "checkered", "ZIEL"
        if yfs == 7:
            return "red", "ROT"
        if phase == 6 or yfs in (1, 2, 3, 4, 6):
            return "yellow", "GELB"
        if pf == 6:
            return "blue", "BLAU"
        if yfs == 5:
            return "white", "WEISS"
        if phase == 5:
            return "green", "GR\u00dcN"
        return "none", "\u2014"

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        base = {
            "green": QColor("#2ecc40"), "yellow": QColor("#ffd400"),
            "blue": QColor("#0a84ff"), "white": QColor("#eef1f5"),
            "red": QColor("#ff3b30"), "checkered": QColor("#eef1f5"),
            "none": QColor(60, 66, 74),
        }[self._flag]
        pad = 10
        cols = 14
        cell = (min(w, h) - 2 * pad) / cols
        rows = max(1, int((h - 2 * pad - 20) / cell))
        ox = (w - cols * cell) / 2.0
        oy = pad
        for r in range(rows):
            for c in range(cols):
                if self._flag == "checkered":
                    col = QColor("#eef1f5") if (r + c) % 2 == 0 else QColor(30, 34, 40)
                elif self._flag == "none":
                    col = QColor(48, 54, 62)
                else:
                    col = QColor(base)
                    if (r + c) % 3 == 0:
                        col = col.darker(118)
                p.setBrush(col); p.setPen(Qt.NoPen)
                p.drawEllipse(QRectF(ox + c * cell + cell * 0.12,
                                     oy + r * cell + cell * 0.12,
                                     cell * 0.76, cell * 0.76))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold)); p.setPen(self._fg())
        p.drawText(QRectF(0, h - 20, w, 16), Qt.AlignCenter, self._label)
        p.end()


class LapGraphOverlayWindow(OverlayStyleMixin, QWidget):
    """0.5.1.0: Rundenzeiten-Graph (Bild 3). Sammelt abgeschlossene Rundenzeiten
    (Erkennung ueber Rundenwechsel) und zeichnet sie als Linie; gruen = saubere
    schnelle Runde, rot = langsam/Ausreisser. Overlay-lokale Historie."""

    MAXN = 24

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Rundenzeiten-Graph")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(300, 190)
        self.setMinimumSize(220, 140)
        self._times = []
        self._last_lap = None
        self._drag = None

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if s is not None:
            lap = int(getattr(s, "lap_number", 0) or 0)
            last = float(getattr(s, "last_lap_time", 0.0) or 0.0)
            if self._last_lap is None:
                self._last_lap = lap
            elif lap != self._last_lap:
                self._last_lap = lap
                if 20.0 < last < 1800.0:
                    self._times.append(last)
                    if len(self._times) > self.MAXN:
                        del self._times[0:len(self._times) - self.MAXN]
        self.update()

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        self._draw_title(p, QRectF(12, 6, w - 20, 16), "RUNDENZEITEN-GRAPH")
        ts = self._times
        if len(ts) < 2:
            p.setPen(self._muted()); p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "sammle Rundenzeiten \u2026")
            p.end(); return
        best = min(ts)
        lo = best * 0.98
        hi = max(max(ts), best * 1.05)
        ml, mr, mt, mb = 52, 12, 28, 20
        pw = w - ml - mr; ph = h - mt - mb
        def X(i): return ml + pw * (i / (len(ts) - 1))
        def Y(v): return mt + ph * (1 - (v - lo) / (hi - lo + 1e-6))
        p.setFont(QFont("Segoe UI", 7))
        for k in range(4):
            gy = mt + ph * k / 3.0
            p.setPen(QPen(self._faint(45), 1, Qt.DotLine))
            p.drawLine(QPointF(ml, gy), QPointF(w - mr, gy))
            val = hi - (hi - lo) * k / 3.0
            p.setPen(self._muted())
            p.drawText(QRectF(2, gy - 7, ml - 6, 14), Qt.AlignRight | Qt.AlignVCenter, fmt_lap_time(val))
        thr = best * 1.03
        for i in range(1, len(ts)):
            col = QColor("#3fb950") if ts[i] <= thr else QColor("#f85149")
            p.setPen(QPen(col, 2))
            p.drawLine(QPointF(X(i - 1), Y(ts[i - 1])), QPointF(X(i), Y(ts[i])))
        for i, v in enumerate(ts):
            col = QColor("#3fb950") if v <= thr else QColor("#f85149")
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(X(i) - 3, Y(v) - 3, 6, 6))
        p.end()


class OvertakeOverlayWindow(OverlayStyleMixin, QWidget):
    """0.5.1.0: Ueberholalarm (Bild 5). Listet Fahrzeuge, die auf der Strecke
    hinter mir sind, mit Zeitabstand (= Streckenabstand / eigenes Tempo) bis sie
    mich erreichen. Position, Klasse (farbig), Fahrername. Rot < 1 s, orange
    < 2 s, Pfeil = kommt naeher. Hersteller-Logos liefert das SharedMemory nicht."""

    CLASS_COLORS = [
        ("GROUP C", QColor("#ff3b30")), ("GTR 1", QColor("#ff3b30")), ("P1", QColor("#ff3b30")), ("HYPER", QColor("#ff3b30")),
        ("P2", QColor("#ffd400")), ("LMP", QColor("#ffd400")),
        ("GTR 2", QColor("#ff375f")), ("GTE", QColor("#ff375f")), ("GT2", QColor("#ff375f")),
        ("GTR 3", QColor("#ff9f0a")), ("GT3", QColor("#ff9f0a")),
        ("GTR 4", QColor("#33d1e0")), ("GT4", QColor("#33d1e0")),
        ("DTM", QColor("#58a6ff")), ("WTC", QColor("#3fb950")), ("TOURING", QColor("#3fb950")),
        ("CUP", QColor("#bf5af2")), ("GT", QColor("#ff9f0a")),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Ueberholalarm")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(300, 176)
        self.setMinimumSize(220, 80)
        self._rows = []
        self._prev = {}
        self._drag = None

    def _class_color(self, vclass):
        u = (vclass or "").upper()
        for key, col in self.CLASS_COLORS:
            if key in u:
                return col
        return QColor("#8a97a8")

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        rows = []
        if s is not None:
            spd = float(getattr(s, "speed_kmh", 0.0) or 0.0) / 3.6
            if spd > 3.0:
                cur = {}
                for e in getattr(s, "opponents_behind", ()):
                    try:
                        place, driver, vclass, dist = int(e[0]), str(e[1]), str(e[2]), float(e[3])
                    except Exception:
                        continue
                    gap = dist / spd
                    prev = self._prev.get(driver)
                    closing = prev is not None and gap < prev - 0.02
                    cur[driver] = gap
                    rows.append((place, driver, vclass, gap, closing))
                self._prev = cur
        rows.sort(key=lambda r: r[3])
        self._rows = rows[:5]
        self.update()

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        self._draw_title(p, QRectF(10, 6, w - 20, 16), "\u00dcBERHOLALARM")
        rows = self._rows
        if not rows:
            p.setPen(self._muted()); p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "frei hinten")
            p.end(); return
        y = 26.0
        rh = min(30.0, (h - 30) / max(len(rows), 1))
        for place, driver, vclass, gap, closing in rows:
            ccol = self._class_color(vclass)
            p.setPen(Qt.NoPen); p.setBrush(self._panel())
            p.drawRoundedRect(QRectF(8, y, w - 16, rh - 4), 6, 6)
            p.setBrush(ccol); p.drawRoundedRect(QRectF(12, y + 3, 34, rh - 10), 4, 4)
            p.setFont(QFont("Segoe UI", 9, QFont.Bold)); p.setPen(QColor("#0d1117"))
            p.drawText(QRectF(12, y + 3, 34, rh - 10), Qt.AlignCenter, str(place) if place else "\u2014")
            p.setFont(QFont("Segoe UI", 9, QFont.DemiBold)); p.setPen(self._fg())
            short = (vclass or "").upper()[:5]
            p.drawText(QRectF(52, y, w - 130, rh - 4), Qt.AlignVCenter | Qt.AlignLeft, f"{short}  {driver}")
            gcol = QColor("#f85149") if gap < 1.0 else (QColor("#ff9f0a") if gap < 2.0 else self._muted())
            p.setFont(QFont("Segoe UI", 11, QFont.Bold)); p.setPen(gcol)
            arrow = " \u25b2" if closing else ""
            p.drawText(QRectF(w - 78, y, 66, rh - 4), Qt.AlignVCenter | Qt.AlignRight, f"+{gap:.1f}{arrow}")
            y += rh
        p.end()


class DamageModel:
    """RaceRoom: Fahrzeugschaeden aus dem Shared-Memory-Block ``car_damage`` (Aerodynamik,
    Aufhaengung, Motor, Getriebe). Der Adapter (raceroom_sm.py) liefert sie bereits als
    Schaden in Prozent (0 = unbeschaedigt, -1 = nicht verfuegbar); dazu kommen Reifen-Flatspots.

    Die Warn-/Schwerschwellen sind Kalibrierwerte in damage_model.json - das Overlay zeigt
    die Rohwerte an, damit sie anhand echter Faelle nachgezogen werden koennen."""

    PARTS = (("aero", "Aerodynamik"), ("suspension", "Aufh\u00e4ngung"),
             ("engine", "Motor"), ("transmission", "Getriebe"))
    DEFAULTS = {"warn_pct": 8.0, "severe_pct": 25.0}

    def __init__(self, config_path=None):
        self.cfg = dict(self.DEFAULTS)
        self.config_path = config_path
        self.load()
        self.reset()

    def load(self):
        if not self.config_path:
            return
        try:
            import json
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in self.DEFAULTS:
                if k in data:
                    self.cfg[k] = float(data[k])
        except Exception:
            pass

    def save(self):
        if not self.config_path:
            return
        try:
            import json
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception:
            pass

    def reset(self):
        self.cur = {k: None for k, _ in self.PARTS}     # aktueller Schaden je Teil (None = unbekannt)
        self.peak = {k: 0.0 for k, _ in self.PARTS}     # hoechster je gesehener Wert
        self.flats = [False, False, False, False]
        self._veh = None
        self.saw_channel = False

    def update(self, s):
        if s is None:
            return
        veh = str(getattr(s, "vehicle_name", "") or "")
        if self._veh is None:
            self._veh = veh
        elif veh != self._veh:
            self.reset()
            self._veh = veh
        for k, _label in self.PARTS:
            try:
                v = float(getattr(s, f"dmg_{k}_pct", -1.0))
            except Exception:
                v = -1.0
            if v >= 0.0:
                self.saw_channel = True
                self.cur[k] = v
                if v > self.peak[k]:
                    self.peak[k] = v
            else:
                self.cur[k] = None
        for i, k in enumerate(("fl", "fr", "rl", "rr")):
            if bool(getattr(s, f"tire_{k}_flat", False)):
                self.flats[i] = True

    # ---- Bewertung ----
    def worst_pct(self):
        vals = [v for v in self.cur.values() if v is not None]
        return max(vals) if vals else 0.0

    def index_pct(self):
        return max(0.0, min(100.0, self.worst_pct()))

    def severe(self):
        return self.worst_pct() >= float(self.cfg["severe_pct"]) or any(self.flats)

    def any_damage(self):
        return self.worst_pct() >= 1.0 or any(self.flats)

    def repair_hint(self):
        if any(self.flats):
            return ("Reifenschaden \u2013 sofort Box", "bad")
        w = self.worst_pct()
        if w >= float(self.cfg["severe_pct"]):
            return ("Reparatur n\u00f6tig \u2013 Box ansteuern", "bad")
        if w >= float(self.cfg["warn_pct"]):
            return ("Reparatur beim n\u00e4chsten Stopp", "warn")
        if self.any_damage():
            return ("leichter Schaden \u2013 beobachten", "warn")
        return ("keine Reparatur n\u00f6tig", "good")

    def diagnostics(self):
        """Rohwerte, damit sichtbar ist, was das Spiel tatsaechlich liefert."""
        if not self.saw_channel:
            return "Schadenskanal still (kein Wert vom Spiel)"
        return " \u00b7 ".join(
            (f"{k[:3]} {self.cur[k]:.0f}" if self.cur[k] is not None else f"{k[:3]} \u2014")
            for k, _l in self.PARTS)


class DamageOverlayWindow(OverlayStyleMixin, QWidget):
    """Fahrzeugschaeden ueber das DamageModel (RaceRoom car_damage). Doppelklick setzt nach
    einer Reparatur zurueck. Unten stehen die Rohwerte aller Teile."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Schaden Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(258, 212)
        self.setMinimumSize(220, 186)
        self._d = None
        self._m = None
        self._drag = None

    def update_from_main(self, main):
        self._d = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        self._m = getattr(main, "damage_model", None)
        self.update()

    def mousePressEvent(self, ev): self._drag_start(ev)
    def mouseMoveEvent(self, ev): self._drag_move(ev)
    def mouseReleaseEvent(self, ev): self._drag = None

    def mouseDoubleClickEvent(self, ev):   # nach Reparatur zuruecksetzen
        if self._m is not None:
            self._m.reset()
        self.update()

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
        self._draw_title(p, QRectF(10, 6, w - 20, 16), "SCHADEN")
        s = self._d
        if s is None:
            p.setPen(self._muted()); p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "warte auf Telemetrie")
            p.end(); return
        m = self._m
        if m is None:
            p.setPen(self._muted())
            p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "Schadensmodell nicht aktiv")
            p.end(); return
        pct = m.index_pct()
        warn, severe = float(m.cfg["warn_pct"]), float(m.cfg["severe_pct"])

        def lvl_col(v):
            if v is None:
                return self._muted()
            return QColor("#f85149") if v >= severe else QColor("#e3b341") if v >= warn else QColor("#3fb950")

        col = QColor("#f85149") if m.severe() else QColor("#e3b341") if m.any_damage() else QColor("#3fb950")
        fv = QFont(); fv.setPointSize(22); fv.setBold(True); p.setFont(fv); p.setPen(col)
        p.drawText(QRectF(10, 22, w - 20, 30), Qt.AlignLeft, f"{pct:.0f} %")
        fs = QFont(); fs.setPointSize(9); p.setFont(fs); p.setPen(self._muted())
        p.drawText(QRectF(10, 30, w - 20, 22), Qt.AlignRight, "schlimmster Teilschaden")
        bx, by, bw, bh = 10, 56, w - 20, 9
        p.setPen(Qt.NoPen); p.setBrush(QColor(31, 39, 52) if self._st() != "light" else QColor(226, 231, 238))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
        p.setBrush(col); p.drawRoundedRect(QRectF(bx, by, max(bw * min(pct / 100.0, 1.0), 3), bh), 4, 4)

        def row(y, key, val, color=None):
            self._kv_row(p, w, y, key, val, color)

        y = 72
        for key, label in m.PARTS:
            v = m.cur.get(key)
            row(y, label, "\u2014" if v is None else f"{v:.0f} %", lvl_col(v))
            y += 18
        names = ["VL", "VR", "HL", "HR"]
        bad = [names[i] for i in range(4) if m.flats[i]]
        row(y, "Reifen", (", ".join(bad) + " platt") if bad else "in Ordnung",
            QColor("#f85149") if bad else QColor("#3fb950"))
        hint, kind = m.repair_hint()
        hc = {"bad": QColor("#f85149"), "warn": QColor("#e3b341"), "good": QColor("#3fb950")}.get(kind, self._fg())
        fh = QFont(); fh.setPointSize(9); fh.setBold(True); p.setFont(fh)
        p.setPen(hc); p.drawText(QRectF(10, h - 32, w - 20, 16), Qt.AlignLeft, hint)
        fdg = QFont(); fdg.setPointSize(7); p.setFont(fdg); p.setPen(self._muted())
        p.drawText(QRectF(10, h - 15, w - 20, 12), Qt.AlignLeft, "Quelle: RaceRoom \u00b7 " + m.diagnostics())
        p.end()


# ---------------------------------------------------------------------------
# 0.2.37: Kurvennamen-Overlay. RaceRoom liefert keine Kurvennamen ueber das
# Shared Memory, deshalb erkennt PitBoss die Kurven selbst aus einer gefahrenen
# Runde (heading_deg pro Streckenmeter) und nummeriert sie in Fahrtrichtung
# (K1, K2, ...). Eigene Namen pro Strecke landen in corner_names.json und sind
# im Dialog "Kurven benennen ..." pflegbar.
# ---------------------------------------------------------------------------
CORNER_NAMES_PATH = EXPORT_DIR / "corner_names.json"  # 0.2.37


def load_corner_names() -> dict:
    """0.2.37: {"Strecke": {"1": "Name", ...}} laden; ungueltig -> leeres Dict."""
    try:
        raw = json.loads(CORNER_NAMES_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_corner_names(data: dict) -> bool:
    """0.2.37: Kurvennamen in Dokumente\\PitBoss R3E\\corner_names.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        CORNER_NAMES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def detect_corners_from_rows(rows, min_total_deg=25.0, bin_m=10.0, diff_span_bins=3):
    """0.2.37: Kurven aus einer abgeschlossenen Runde erkennen.

    heading_deg wird pro 10-m-Bin vektoriell gemittelt (sicher gegen den
    0/360-Umbruch). Eine Kurve ist ein Bereich, in dem sich die Richtung
    ueber 30 m deutlich aendert; gezaehlt wird die Gesamtdrehung des
    Bereichs (>= min_total_deg). Rueckgabe: in Fahrtrichtung sortierte Liste
    [{"idx", "dir" ("L"/"R"), "turn_deg", "lap_dist_m"}].
    """
    pts = []
    for r in rows:
        d = float(getattr(r, "lap_dist_m", -1.0) or 0.0)
        h = float(getattr(r, "heading_deg", 0.0) or 0.0)
        v = float(getattr(r, "speed_kmh", 0.0) or 0.0)
        if d >= 0 and v >= 5.0:
            pts.append((d, h))
    if len(pts) < 60:
        return []
    pts.sort(key=lambda p: p[0])
    bins = {}
    for d, h in pts:
        k = int(d // bin_m)
        b = bins.setdefault(k, [0.0, 0.0, 0])
        rad = math.radians(h)
        b[0] += math.cos(rad)
        b[1] += math.sin(rad)
        b[2] += 1
    keys = sorted(bins)

    def heading_of(k):
        b = bins[k]
        return math.degrees(math.atan2(b[1], b[0])) % 360.0

    def hdelta(k1, k2):
        return ((heading_of(k2) - heading_of(k1) + 180.0) % 360.0) - 180.0

    n = len(keys)
    strength = {}
    for i in range(n):
        j = min(i + diff_span_bins, n - 1)
        strength[keys[i]] = abs(hdelta(keys[i], keys[j]))
    corners = []
    in_corner = False
    start_i = 0

    def _close(end_i):
        total = hdelta(keys[start_i], keys[end_i])
        if abs(total) >= min_total_deg:
            apex_i = start_i + max(range(end_i - start_i + 1),
                                    key=lambda o: strength[keys[start_i + o]])
            corners.append({
                "dir": "L" if total > 0 else "R",
                "turn_deg": round(abs(total), 1),
                "lap_dist_m": round(keys[apex_i] * bin_m, 1),
            })

    for i in range(n):
        s = strength[keys[i]]
        if not in_corner and s >= 7.0:
            in_corner = True
            start_i = i
        elif in_corner and s < 4.0:
            _close(i - 1)
            in_corner = False
    if in_corner:
        _close(n - 1)
    corners.sort(key=lambda c: c["lap_dist_m"])
    for i, c in enumerate(corners, 1):
        c["idx"] = i
    return corners


class CornerNameOverlayWindow(OverlayStyleMixin, QWidget):
    """0.2.37: kleines Overlay mit der naechsten Kurve: Name, Richtungspfeil
    und Distanz in Metern. Basis: automatisch erkannte Kurven der Strecke
    plus eigene Namen aus corner_names.json ('Kurven benennen ...')."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(250, 96)
        self._track = ""
        self._name = "-"
        self._dir = ""
        self._dist_m = None
        self._drag = None

    def set_info(self, track, name, dir_, dist_m):
        self._track = track or ""
        self._name = name or "-"
        self._dir = dir_ or ""
        self._dist_m = dist_m
        self.update()

    def mousePressEvent(self, e):
        try:
            gp = e.globalPosition().toPoint()
            self._drag = (gp, self.pos())
        except Exception:
            self._drag = None

    def mouseMoveEvent(self, e):
        if self._drag:
            gp = e.globalPosition().toPoint()
            self.move(self._drag[1].x() + gp.x() - self._drag[0].x(),
                      self._drag[1].y() + gp.y() - self._drag[0].y())

    def mouseReleaseEvent(self, e):
        self._drag = None

    def paintEvent(self, ev):
        p = self._begin_paint()
        self._paint_frame(p, self._lw(), self._lh())
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(self._muted()))
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        head = "NAECHSTE KURVE" + ((" - " + self._track) if self._track else "")
        p.drawText(QRectF(12, 8, self._lw() - 24, 16), Qt.AlignLeft, head)
        fg = self._fg()
        f2 = QFont()
        f2.setPointSize(15 if len(self._name) <= 14 else 11)
        f2.setBold(True)
        p.setFont(f2)
        p.setPen(QPen(fg))
        arrow = "L" if self._dir == "L" else ("R" if self._dir == "R" else "")
        label = ((arrow + "  ") if arrow else "") + self._name
        p.drawText(QRectF(12, 26, self._lw() - 24, 34), Qt.AlignLeft, label)
        f3 = QFont()
        f3.setPointSize(10)
        p.setFont(f3)
        if self._dist_m is None:
            p.setPen(QPen(self._muted()))
            p.drawText(QRectF(12, 60, self._lw() - 24, 22), Qt.AlignLeft,
                       "keine Kurvendaten - erst eine Runde fahren")
        else:
            p.setPen(QPen(QColor("#e8212b")))
            p.drawText(QRectF(12, 60, self._lw() - 24, 22), Qt.AlignLeft,
                       "in " + str(int(round(self._dist_m))) + " m")
        p.end()

class OverlayWindow(OverlayStyleMixin, QWidget):
    """Schlankes Always-on-top Monitor/Coach-Overlay im HUD-Stil.
    Kein VR-Overlay und kein Click-through: stabil und verschiebbar.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Coach Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(1.0)
        self.resize(330, 118)
        self.setMinimumSize(300, 108)
        self._drag_pos = None
        self._flatspot_hold = {"VL": 0, "VR": 0, "HL": 0, "HR": 0}
        self._flatspot_text = {"VL": "OK", "VR": "OK", "HL": "OK", "HR": "OK"}
        self.setStyleSheet("""
            QWidget { background:transparent; color:#ffffff; font-size:12px; }
            QLabel { color:#ffffff; background:transparent; }
            QFrame { background:transparent; border:0px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(2)

        header = QHBoxLayout()
        title = QLabel("COACH")
        title.setObjectName("ovlTitle")  # 0.4.9.7: Farbe kommt aus _restyle
        self.compact_status = QLabel("LIVE")
        self.compact_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.compact_status.setStyleSheet("font-size:12px;font-weight:bold;color:#3fb950;background:transparent;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.compact_status)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(1)
        self.values = {}
        # Minimal-Overlay: Runden-, Speed- und Reifendaten sind im Spiel-HUD bzw. Reifen-Overlay sichtbar.
        # Dieses Fenster zeigt nur noch Referenz/Delta/Coach.
        rows = [
            ("Referenz", "—"),
            ("Delta", "—"),
            ("Coach", "—"),
        ]
        for r, (name, val) in enumerate(rows):
            k = QLabel(name)
            k.setFixedWidth(58)
            k.setObjectName("ovlKey")  # 0.4.9.7
            v = QLabel(val)
            v.setWordWrap(False)
            v.setObjectName("ovlVal")  # 0.4.9.7
            grid.addWidget(k, r, 0)
            grid.addWidget(v, r, 1)
            self.values[name] = v
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

    def paintEvent(self, event):
        # Gleicher halbtransparenter HUD-Look wie Reifen-Overlay, aber kompakter.
        painter = self._begin_paint()
        self._paint_frame(painter, self._lw(), self._lh())

    def _restyle(self):
        light = self._st() == "light"
        c = "#16161a" if light else "#f1f1f3"
        key = "#666671" if light else "#8f8f99"
        self.setStyleSheet(
            "QWidget { background:transparent; color:%s; font-size:12px; }"
            "QLabel { color:%s; background:transparent; }"
            "QLabel#ovlTitle { color:%s; font-size:12px; font-weight:bold; }"
            "QLabel#ovlKey { color:%s; font-size:10px; }"
            "QLabel#ovlVal { color:%s; font-size:11px; font-weight:bold; }"
            % (c, c, c, key, c))
        self._restyle_status()  # 0.4.9.7

    def _sem_color(self, kind):
        """0.4.9.7: Warnfarben im hellen Design abdunkeln, sonst unlesbar."""
        light = self._st() == "light"
        if kind == "bad":
            return "#c62828" if light else "#f85149"
        return "#8a6100" if light else "#d29922"

    def _restyle_status(self):
        lab = getattr(self, "compact_status", None)
        if lab is None:
            return
        kind = getattr(self, "_status_kind", "warn")
        lab.setStyleSheet("font-size:12px;font-weight:bold;color:%s;background:transparent;"
                          % self._sem_color(kind))

    def _start_drag(self, event):
        try:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return True
        except Exception:
            return False

    def _move_drag(self, event):
        try:
            if self._drag_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
                return True
        except Exception:
            pass
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_drag(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._move_drag(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def set_value(self, key: str, value: str):
        if key in self.values:
            self.values[key].setText(value)

    def _short_ref(self, main) -> str:
        try:
            txt = main.reference_display_label(short=True)
            # Sehr kurze Anzeige fürs Overlay.
            txt = txt.replace("Silverstone National Circuit | ", "")
            if txt in ("Auto / offen", "—") and getattr(main, "live_best_reference_lap", None) is not None:
                return f"Live-Ref Lap {main.live_best_reference_lap}"
            if len(txt) > 34:
                txt = txt[:31] + "…"
            return txt
        except Exception:
            return "—"

    def update_from_main(self, main):
        last = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if main.recording:
            self.compact_status.setText("● REC")
            self._status_kind = "bad"; self._restyle_status()  # 0.4.9.7
        elif last:
            self.compact_status.setText("● LIVE")
            self.compact_status.setStyleSheet("font-size:12px;font-weight:bold;color:#3fb950;background:transparent;")
        else:
            self.compact_status.setText("WARTET")
            self._status_kind = "warn"; self._restyle_status()  # 0.4.9.7

        # Runde/Speed/Reifen bleiben bewusst ausgeblendet: Spiel-HUD + Reifen-Overlay übernehmen das.
        self.set_value("Referenz", self._short_ref(main))

        if getattr(main, "live_delta_s", None) is not None:
            self.set_value("Delta", f"{main.live_delta_s:+.3f} s")
            coach = getattr(main, "live_coach_line", "Live-Vergleich aktiv") or "Live-Vergleich aktiv"
            if len(coach) > 42:
                coach = coach[:39] + "…"
            self.set_value("Coach", coach)
        elif getattr(main, "segment_deltas", None) and getattr(main, "compare_lap", None):
            total = sum(d.delta_s for d in main.segment_deltas)
            self.set_value("Delta", f"Lap {main.compare_lap.lap_number}: {total:+.3f} s")
            zones = main.grouped_problem_zones() if main.segment_deltas else []
            if zones:
                z = zones[0]
                sec = main.sector_name_for_m(z[0])  # 0.2.9
                sec_txt = f" ({sec})" if sec else ""
                self.set_value("Coach", f"Zone {z[0]}-{z[1]} m{sec_txt} · {z[2]:+.3f}s")
            else:
                self.set_value("Coach", "keine große Verlustzone")
        else:
            self.set_value("Delta", "Referenz laden")
            self.set_value("Coach", "Live sammelt Daten")


class TireMiniWidget(OverlayStyleMixin, QWidget):
    """Skalierbare Reifenanzeige (VR-tauglich). 0.5.9.4: drei Balken je Zone
    (A/M/I). Balkenhoehe + %-Wert darueber = Verschleiss der Zone, Ampel
    (>=75 gruen / >=40 gelb / sonst rot); Zonentemperatur darunter. Kopfzeile:
    Druck (bar) + Carcass-Temp. Ohne Pro-Zone-Quelle zeigen alle drei denselben
    Verschleiss (wear_zones-Fallback). Flat/Lock-Warnung nur wenn warn_enabled."""
    def __init__(self, name: str, value_side: str = "right"):
        super().__init__()
        self.name = name
        self.value_side = value_side
        self.pressure_kpa = 0.0
        self.out_t = 0.0; self.mid_t = 0.0; self.in_t = 0.0
        self.carcass = 0.0
        self.wear = 0.0
        self.wear_out = 0.0; self.wear_mid = 0.0; self.wear_in = 0.0  # 0.5.5.1: pro Zone (MFD)
        self.wear_trend = 0.0
        self.grip_score = 0
        self.flat_status = "OK"
        self.warn_enabled = True
        self.scale = 1.0
        self._apply_min_size()
        self.setToolTip("Reifen: 3 Balken je Zone (A/M/I=aussen/mitte/innen). "
                        "Balkenhoehe + % darueber = Verschleiss (gruen >=75 %, gelb >=40 %, "
                        "rot darunter). Balken- und Zahlenfarbe = Zonentemperatur nach dem "
                        "Temperaturfenster des Spiels (blau kalt, gruen optimal, orange warm, rot heiss). "
                        "Fusszeile: Rad + Druck (bar). Flat-/ABS-/Lock-Warnung nur wenn aktiviert.")

    def _apply_min_size(self):
        self.setMinimumSize(int(196 * self.scale), int(172 * self.scale))

    def set_scale(self, scale):
        self.scale = max(0.6, min(2.5, float(scale) or 1.0))
        self._apply_min_size()
        self.updateGeometry()
        self.update()

    def set_data(self, pressure, out_t, mid_t, in_t, carcass, wear, grip_score=0,
                 flat_status="OK", wear_trend=0.0, warn_enabled=True, wear_zones=None):
        self.pressure_kpa = pressure or 0.0
        self.out_t = out_t or 0.0; self.mid_t = mid_t or 0.0; self.in_t = in_t or 0.0
        self.carcass = carcass or 0.0
        self.wear = max(0.0, min(100.0, wear or 0.0))
        if wear_zones and len(wear_zones) == 3:
            self.wear_out, self.wear_mid, self.wear_in = [max(0.0, min(100.0, x or 0.0)) for x in wear_zones]
        else:
            self.wear_out = self.wear_mid = self.wear_in = self.wear
        self.wear_trend = wear_trend or 0.0
        self.grip_score = int(max(0, min(100, grip_score or 0)))
        self.flat_status = flat_status or "OK"
        self.warn_enabled = bool(warn_enabled)
        self.update()

    def rest_color(self) -> QColor:
        if self.wear >= 85:
            return QColor(25, 225, 45)
        if self.wear >= 65:
            return QColor(235, 215, 45)
        if self.wear >= 45:
            return QColor(255, 145, 25)
        return QColor(240, 40, 30)

    @staticmethod
    def _wear_color(wv):
        # 0.5.5.1: Farbe nach Rest-Verschleiss: viel Rest = gruen, abgefahren = rot
        if wv >= 85:
            return QColor(25, 225, 45)
        if wv >= 65:
            return QColor(235, 215, 45)
        if wv >= 45:
            return QColor(255, 145, 25)
        return QColor(240, 40, 30)

    @staticmethod
    def _temp_pct(t):
        """0.5.5.0: Zonentemperatur als Prozent im Arbeitsfenster (80-100 C = 100 %).
        Einzige echte Pro-Zone-Groesse in RaceRoom ist die Temperatur - der Verschleiss
        (tire_wear) ist ein Einzelwert. Deshalb speist die Temperatur die %-Balken."""
        if t <= 0:
            return 0.0
        if 80.0 <= t <= 100.0:
            return 100.0
        if t < 80.0:
            return max(0.0, (t - 55.0) / 25.0 * 100.0)
        return max(0.0, (120.0 - t) / 20.0 * 100.0)

    @staticmethod
    def _bar_color(wear):
        # 0.5.9.1: Verschleiss-Ampel nach Vorgabe:
        #   >= 75 % Rest -> gruen, >= 40 % -> gelb, sonst rot.
        if wear >= 75.0:
            return QColor(25, 225, 45)
        if wear >= 40.0:
            return QColor(235, 205, 40)
        return QColor(240, 45, 30)

    def paintEvent(self, event):
        p = self._begin_paint()
        p.setRenderHint(QPainter.Antialiasing)
        w = self._lw(); h = self._lh()

        def F(px, bold=False):
            f = p.font(); f.setPointSizeF(max(6.0, px)); f.setBold(bold); p.setFont(f)

        # 0.5.9.5: Layout nach Mockup. Pro Zone (A/M/I = aussen/mitte/innen):
        #   %-Wert oben + Balkenhoehe = Verschleiss (Ampel >=75 gruen/>=40 gelb/
        #   sonst rot), Zonentemperatur darunter. Fusszeile: Rad-ID, Druck (bar),
        #   Carcass-Temp. HINWEIS: RaceRoom-Shared-Memory hat tire_wear nur EINMAL pro Rad
        #   -> ohne Pro-Zone-Quelle zeigen alle drei denselben Wert (wear_zones-
        #   Fallback); differenziert sich automatisch, sobald tireinfo/MFD liefert.
        zt = [self.out_t, self.mid_t, self.in_t]
        zw = [self.wear_out, self.wear_mid, self.wear_in]
        # 0.5.9.6: schmaler + enger zusammen -> wirkt wie eine Reifen-Lauffflaeche.
        group_w = w * 0.56
        x0 = (w - group_w) / 2.0
        gap = group_w * 0.05
        b_w = (group_w - 2 * gap) / 3.0
        cellw = b_w + gap
        pct_top = h * 0.05; pct_h = h * 0.115
        bar_top = h * 0.20; bar_bot = h * 0.68; bar_h = bar_bot - bar_top
        temp_top = h * 0.70; temp_h = h * 0.12

        # 0.5.9.7: Schriftgroessen skalieren mit dem Overlay UND passen garantiert
        # in die (schmale) Spalte -> Werte bleiben immer lesbar, nie abgeschnitten.
        # Fit gegen den breitesten Fall ("100%"/"100C"), damit alle drei gleich gross.
        def fit_pt(text, max_w, max_h, start):
            f = p.font(); f.setBold(True); s = float(start)
            f.setPointSizeF(max(6.0, s)); fm = QFontMetricsF(f)
            while s > 6.5 and (fm.horizontalAdvance(text) > max_w or fm.height() > max_h):
                s -= 0.5; f.setPointSizeF(s); fm = QFontMetricsF(f)
            return max(6.0, s)
        pct_pt = fit_pt("100%", cellw * 0.98, pct_h, min(cellw * 0.62, h * 0.14))
        temp_pt = fit_pt("100C", cellw * 0.98, temp_h, min(cellw * 0.55, h * 0.12))

        for i in range(3):
            bx = x0 + i * (b_w + gap)
            cellx = bx - gap / 2.0
            wv = max(0.0, min(100.0, zw[i]))
            wc = self._bar_color(wv)
            tc = temp_color_for_tire(zt[i])  # Balken + Temperatur: Farbe nach Temperaturfenster (wie im Spiel)
            # %-Wert oben (Ampelfarbe), skaliert + fit
            F(pct_pt, True); p.setPen(wc)
            p.drawText(QRectF(cellx, pct_top, cellw, pct_h), Qt.AlignCenter, f"{wv:.0f}%")
            # Balken: Track + Fuellung nach Verschleiss
            p.setPen(QPen(self._border(), 1)); p.setBrush(QBrush(self._trackcol()))
            p.drawRoundedRect(QRectF(bx, bar_top, b_w, bar_h), 4, 4)
            fillh = bar_h * (wv / 100.0)
            if fillh > 1.0:
                p.setPen(Qt.NoPen); p.setBrush(QBrush(tc))
                p.drawRoundedRect(QRectF(bx, bar_bot - fillh, b_w, fillh), 4, 4)
            # Zonentemperatur unter dem Balken (temperaturfarbig), skaliert + fit
            F(temp_pt, True); p.setPen(tc)
            p.drawText(QRectF(cellx, temp_top, cellw, temp_h), Qt.AlignCenter, f"{zt[i]:.0f}C")

        # Fusszeile: Rad-ID, Druck (bar), Carcass-Temp
        F(min(h * 0.066, 10), False); p.setPen(self._muted())
        p.drawText(QRectF(0, h * 0.86, w, h * 0.12), Qt.AlignCenter,
                   f"{self.name}   {self.pressure_kpa / 100.0:.2f} bar")

        # Flat/Lock-Warnung (opt-in) rahmt die Balkengruppe
        fs = (self.flat_status or "OK").upper()
        if self.warn_enabled and fs != "OK":
            warn = QColor(255, 60, 50) if ("KRIT" in fs or "PLATT" in fs or "FLAT" in fs) else QColor(255, 165, 35)
            p.setPen(QPen(warn, 2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x0 - 5, bar_top - 4, group_w + 10, bar_h + 8), 6, 6)
            F(min(h * 0.07, 9), True); p.setPen(warn)
            label = "FLAT" if ("PLATT" in fs or "FLAT" in fs) else ("ABS!" if "ABS!" in fs else ("ABS" if "ABS" in fs else ("LOCK!" if ("LOCK!" in fs or "KRIT" in fs) else "LOCK")))
            p.drawText(QRectF(x0 - 5, bar_top - h * 0.075, group_w + 10, h * 0.07), Qt.AlignCenter, label)
        p.end()

class TireOverlayWindow(OverlayStyleMixin, QWidget):
    """Separates, kompaktes Always-on-top Reifenoverlay für Monitor/OBS."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Reifen Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(1.0)
        self.resize(410, 390)
        self.setMinimumSize(400, 380)
        self._drag_pos = None
        self._flatspot_hold = {"VL": 0, "VR": 0, "HL": 0, "HR": 0}
        self._flatspot_text = {"VL": "OK", "VR": "OK", "HL": "OK", "HR": "OK"}
        self.setStyleSheet("""
            QWidget { background:transparent; color:#ffffff; font-size:15px; }
            QLabel { color:#ffffff; background:transparent; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 12)
        root.setSpacing(2)
        title = QLabel("REIFEN")
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("ovlTitle")  # 0.4.9.7
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        root.addWidget(title)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(12)
        self.tire_widgets = {}
        positions = [("VL", 0, 0, "left"), ("VR", 0, 1, "right"), ("HL", 1, 0, "left"), ("HR", 1, 1, "right")]
        for name, row, col, side in positions:
            wid = TireMiniWidget(name, side)
            self.grid.addWidget(wid, row, col)
            self.tire_widgets[name] = wid
            wid.installEventFilter(self)
        root.addLayout(self.grid)
        self.status = QLabel("")
        self.status.setVisible(False)
        title.installEventFilter(self)
        self.installEventFilter(self)
        # VR-Tauglichkeit: Skalierung + Deckkraft. Trend-Basiswerte pro Reifen.
        self.ui_scale = 1.0
        self.ui_opacity = 1.0
        self._wear_start = {}
        self.set_ui_scale(0.975)  # 0.1.2: ein Viertel kleiner als bisher (1.3)

    def set_ui_scale(self, scale):
        self.ui_scale = max(0.7, min(2.2, float(scale) or 1.0))
        for wdg in self.tire_widgets.values():
            wdg.set_scale(self.ui_scale)
        self.grid.setHorizontalSpacing(int(8 * self.ui_scale))
        self.grid.setVerticalSpacing(int(12 * self.ui_scale))
        self.setMinimumSize(int(360 * self.ui_scale), int(340 * self.ui_scale))
        self.resize(int(410 * self.ui_scale), int(390 * self.ui_scale))
        self.update()

    def set_ui_opacity(self, op):
        self.ui_opacity = max(0.25, min(1.0, float(op)))
        self.setWindowOpacity(self.ui_opacity)

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d != 0:
            self.set_ui_scale(self.ui_scale + (0.1 if d > 0 else -0.1))
            event.accept()

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        sm = menu.addMenu("Skalierung")
        for label, val in [("75 %", 0.75), ("100 %", 1.0), ("125 %", 1.25), ("150 %", 1.5), ("175 %", 1.75), ("200 %", 2.0)]:
            sm.addAction(label, lambda v=val: self.set_ui_scale(v))
        om = menu.addMenu("Deckkraft")
        for label, val in [("40 %", 0.4), ("60 %", 0.6), ("75 %", 0.75), ("90 %", 0.9), ("100 %", 1.0)]:
            om.addAction(label, lambda v=val: self.set_ui_opacity(v))
        menu.exec(event.globalPos())

    def paintEvent(self, event):
        # Etwas stärkerer HUD-Hintergrund: transparenter als ein Fenster, aber mit genug Kontrast.
        painter = QPainter(self)
        self._paint_frame(painter, self.width(), self.height())

    def _restyle(self):
        c = "#1b2430" if self._st() == "light" else "#ffffff"
        self.setStyleSheet(
            "QWidget { background:transparent; color:%s; font-size:15px; }"
            "QLabel { color:%s; background:transparent; }"
            "QLabel#ovlTitle { color:%s; font-size:14px; font-weight:bold; }" % (c, c, c))

    def _start_drag(self, event):
        try:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return True
        except Exception:
            return False

    def _move_drag(self, event):
        try:
            if self._drag_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
                return True
        except Exception:
            pass
        return False

    def eventFilter(self, obj, event):
        try:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                return self._start_drag(event)
            if event.type() == event.Type.MouseMove and event.buttons() & Qt.LeftButton:
                return self._move_drag(event)
            if event.type() == event.Type.MouseButtonRelease:
                self._drag_pos = None
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_drag(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._move_drag(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _score_from_grip_hint(self, text: str) -> int:
        import re
        m = re.search(r"(\d+)\s*%", text or "")
        if m:
            return int(m.group(1))
        low = (text or "").lower()
        if "perfekt" in low:
            return 95
        if "hoch" in low or "gut" in low:
            return 85
        if "mittel" in low:
            return 70
        return 50

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if not s:
            return
        rows = [
            ("VL", s.tire_fl_pressure_kpa, s.tire_fl_temp_l_c, s.tire_fl_temp_c_c, s.tire_fl_temp_r_c, s.tire_fl_carcass_c, s.tire_fl_wear_pct, s.tire_fl_flat, s.tire_fl_grip_fract),
            ("VR", s.tire_fr_pressure_kpa, s.tire_fr_temp_l_c, s.tire_fr_temp_c_c, s.tire_fr_temp_r_c, s.tire_fr_carcass_c, s.tire_fr_wear_pct, s.tire_fr_flat, s.tire_fr_grip_fract),
            ("HL", s.tire_rl_pressure_kpa, s.tire_rl_temp_l_c, s.tire_rl_temp_c_c, s.tire_rl_temp_r_c, s.tire_rl_carcass_c, s.tire_rl_wear_pct, s.tire_rl_flat, s.tire_rl_grip_fract),
            ("HR", s.tire_rr_pressure_kpa, s.tire_rr_temp_l_c, s.tire_rr_temp_c_c, s.tire_rr_temp_r_c, s.tire_rr_carcass_c, s.tire_rr_wear_pct, s.tire_rr_flat, s.tire_rr_grip_fract),
        ]
        # Flat/Lock-Warnung nur ohne ABS (mit ABS entstehen Flatspots durch Dreher, nicht durch Lockup).
        warn_enabled = not bool(getattr(s, "abs_on", False))
        for name, pressure, out_t, mid_t, in_t, carc, wear, flat, grip_fract in rows:
            status = main.flatspot_status(flat, grip_fract, s.brake, s.speed_kmh, s) if hasattr(main, "flatspot_status") else "OK"
            if status != "OK":
                self._flatspot_hold[name] = 80
                self._flatspot_text[name] = status
            elif self._flatspot_hold.get(name, 0) > 0:
                self._flatspot_hold[name] -= 1
                status = self._flatspot_text.get(name, "OK")
            else:
                self._flatspot_text[name] = "OK"
            # Verschleiss-Trend im Stint: Rest jetzt minus Rest bei erstem gueltigen Messwert.
            trend = 0.0
            if wear and wear > 0:
                self._wear_start.setdefault(name, wear)
                trend = wear - self._wear_start.get(name, wear)
            self.tire_widgets[name].set_data(pressure, out_t, mid_t, in_t, carc, wear, 0, status, trend, warn_enabled)
        # Keine Statuszeile im Reifen-HUD: möglichst kompakt und störungsfrei.
        return


class PedalOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.7.1: Scrollendes Pedal-/Lenk-Trace-Overlay (History-Graph).
    Zeigt die Roh-Fahrereingabe ueber die Zeit: Gas (gruen, mit Flaeche),
    Bremse (rot), Lenkung (cyan, um die Mittellinie). Keine Kupplung.
    Desktop-Overlay wie das Reifen-Overlay - kein SteamVR; laeuft im VDXR-Mirror mit."""

    HISTORY = 240  # sichtbare Datenpunkte = Fensterbreite in Samples

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Pedal Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # klaut RaceRoom nicht den Fokus
        self.resize(300, 108)
        self.setMinimumSize(180, 70)
        self._thr = []
        self._brk = []
        self._str = []
        self._live = False
        self._drag = None
        self._col_thr = QColor("#3fb950")
        self._col_brk = QColor("#f85149")
        self._col_str = QColor("#c9c9d3")
        self._gear = 0
        self._last_push_ts = time.monotonic()  # 0.5.9.26: fuer sanftes Zwischen-Scrollen
        self._self_timer = QTimer(self)  # eigener Repaint-Takt fuer sanftes Scrollen, nur bei sichtbarem Fenster
        self._self_timer.setInterval(33)  # 0.2.0: 30 Hz (vorher 60 Hz) - halbiert die Last, Scrollen bleibt weich
        self._self_timer.timeout.connect(self._self_tick)

    def _self_tick(self):  # 0.5.9.26
        if self.isVisible():
            self.update()

    def showEvent(self, ev):
        OverlayStyleMixin.showEvent(self, ev)
        self._self_timer.start()  # 0.2.0: Repaint-Takt nur solange das Fenster sichtbar ist

    def hideEvent(self, ev):
        self._self_timer.stop()
        try:
            super().hideEvent(ev)
        except Exception:
            pass

    def _push(self, thr, brk, srt):
        for buf, val in ((self._thr, thr), (self._brk, brk), (self._str, srt)):
            buf.append(val)
            if len(buf) > self.HISTORY:
                del buf[0:len(buf) - self.HISTORY]
        self._last_push_ts = time.monotonic()  # 0.5.9.26

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if not s:
            self._live = False
            self._gear = 0
            self._push(0.0, 0.0, 0.0)  # Trace laeuft weiter, flacht ab
            self.update()
            return
        c01 = lambda v: 0.0 if v < 0 else 1.0 if v > 1 else v
        c11 = lambda v: -1.0 if v < -1 else 1.0 if v > 1 else v
        thr = c01(float(getattr(s, "input_throttle", 0.0) or 0.0))
        brk = c01(float(getattr(s, "input_brake", 0.0) or 0.0))
        srt = c11(float(getattr(s, "input_steering", 0.0) or 0.0))
        self._live = True
        self._gear = int(getattr(s, "gear", 0) or 0)
        self._push(thr, brk, srt)
        self.update()

    # verschiebbar (rahmenlos)
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def _step(self, plot_w):
        return plot_w / (self.HISTORY - 1)

    def _scroll_shift_px(self, plot_w):  # 0.5.9.26: sanfter Zwischen-Scroll statt 100ms-Sprung
        step = self._step(plot_w)
        period = 0.1  # Sample-Intervall (10 Hz Recorder/Live-Tick)
        frac = (time.monotonic() - self._last_push_ts) / period
        return min(step, max(0.0, frac) * step)

    def _path(self, buf, x0, plot_w, y_at, shift_px=0.0):
        path = QPainterPath()
        n = len(buf)
        if n < 2:
            return path
        step = self._step(plot_w)
        start = self.HISTORY - n  # rechtsbuendig: neueste Werte rechts
        for i, v in enumerate(buf):
            x = x0 + (start + i) * step - shift_px
            y = y_at(v)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        return path

    def paintEvent(self, _):
        p = self._begin_paint()
        p.setRenderHint(QPainter.Antialiasing, True)

        # Karte
        self._paint_frame(p, self._lw(), self._lh())

        gutter = 80 if self._lw() > 210 else 0   # 0.5.1.0: Balken rechts (Bild 4)
        ml, mr, mb = 10, 8, 8
        mt = 20 if gutter else 8                   # 0.2.0: Platz fuer die Balken-Beschriftung (war abgeschnitten)
        x0 = ml
        plot_w = self._lw() - ml - mr - gutter
        top = mt
        bottom = self._lh() - mb
        h = bottom - top
        if plot_w <= 2 or h <= 2:
            return

        y_ped = lambda v: bottom - v * h                    # Pedale 0..1 von unten
        mid = top + h / 2.0
        y_str = lambda v: mid - v * (h / 2.0) * 0.9          # Lenkung -1..1 um die Mitte

        # Mittellinie (Lenkung = 0)
        p.setPen(QPen(QColor(70, 78, 88), 1, Qt.DashLine))
        p.drawLine(int(x0), int(mid), int(x0 + plot_w), int(mid))

        # Gas: Flaeche + Linie
        shift_px = self._scroll_shift_px(plot_w)  # 0.5.9.26
        thr_path = self._path(self._thr, x0, plot_w, y_ped, shift_px)
        if not thr_path.isEmpty():
            first_x = x0 + (self.HISTORY - len(self._thr)) * self._step(plot_w) - shift_px
            fill = QPainterPath(thr_path)
            fill.lineTo(x0 + plot_w, bottom)
            fill.lineTo(first_x, bottom)
            fill.closeSubpath()
            fc = QColor(self._col_thr); fc.setAlpha(55)
            p.setPen(Qt.NoPen); p.setBrush(fc); p.drawPath(fill)
            p.setPen(QPen(self._col_thr, 2)); p.setBrush(Qt.NoBrush); p.drawPath(thr_path)

        # Bremse: Linie
        brk_path = self._path(self._brk, x0, plot_w, y_ped, shift_px)
        if not brk_path.isEmpty():
            p.setPen(QPen(self._col_brk, 2)); p.setBrush(Qt.NoBrush); p.drawPath(brk_path)

        # Lenkung: Linie um die Mitte
        str_path = self._path(self._str, x0, plot_w, y_str, shift_px)
        if not str_path.isEmpty():
            p.setPen(QPen(self._col_str, 1.6)); p.setBrush(Qt.NoBrush); p.drawPath(str_path)

        # Mini-Legende
        f = QFont("Segoe UI", 7, QFont.DemiBold)
        p.setFont(f)
        lx = x0 + 2
        for label, col in (("GAS", self._col_thr), ("BREMSE", self._col_brk), ("LENK", self._col_str)):
            p.setPen(col)
            p.drawText(int(lx), int(top + 8), label)
            lx += p.fontMetrics().horizontalAdvance(label) + 10

        # 0.5.1.0: rechte Balken - Bremse / Gang / Gas (Bild 4)
        if gutter > 0:
            cur_thr = self._thr[-1] if self._thr else 0.0
            cur_brk = self._brk[-1] if self._brk else 0.0
            gw = 12
            gx = x0 + plot_w + 10
            def _vbar(bx, frac, col, cap):
                p.setPen(Qt.NoPen); p.setBrush(self._trackcol())
                p.drawRoundedRect(QRectF(bx, top, gw, h), 2, 2)
                fh = max(0.0, min(1.0, frac)) * h
                p.setBrush(col); p.drawRoundedRect(QRectF(bx, bottom - fh, gw, fh), 2, 2)
                fc = QFont("Segoe UI", 7, QFont.DemiBold); p.setFont(fc); p.setPen(self._muted())
                p.drawText(QRectF(bx - 6, top - 14, gw + 12, 12), Qt.AlignCenter, cap)
            _vbar(gx, cur_brk, self._col_brk, str(int(round(cur_brk * 100))))
            gearx = gx + gw + 10
            p.setFont(QFont("Segoe UI", 15, QFont.Bold)); p.setPen(self._fg())
            gtxt = str(self._gear) if self._gear > 0 else ("N" if self._gear == 0 else "R")
            p.drawText(QRectF(gearx - 3, mid - 13, 24, 26), Qt.AlignCenter, gtxt)
            p.setFont(QFont("Segoe UI", 7, QFont.DemiBold)); p.setPen(self._muted())
            p.drawText(QRectF(gearx - 9, top - 14, 36, 12), Qt.AlignCenter, "GANG")
            _vbar(gearx + 26, cur_thr, self._col_thr, str(int(round(cur_thr * 100))))
        if not self._live:
            p.setPen(QColor(RR_RED)); p.setFont(f)
            p.drawText(self.rect().adjusted(0, 2, -6, 0), Qt.AlignRight | Qt.AlignTop, "warte auf Daten")


class LinkCard(QFrame):
    """0.2.0: klickbare Kachel, die eine Web-Seite im Standardbrowser oeffnet."""
    def __init__(self, title: str, subtitle: str, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self.setObjectName("linkCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(url)
        self.setMinimumHeight(104)
        row = QHBoxLayout(self); row.setContentsMargins(24, 14, 24, 14)
        col = QVBoxLayout(); col.setSpacing(4); col.addStretch(1)
        t = QLabel(title); t.setObjectName("linkCardTitle")
        sub = QLabel(subtitle); sub.setObjectName("linkCardSub")
        arrow = QLabel("\u2197"); arrow.setObjectName("linkCardArrow")
        for lab in (t, sub, arrow):
            lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        f = sub.font(); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2); sub.setFont(f)
        col.addWidget(t); col.addWidget(sub)
        row.addLayout(col, 1); row.addWidget(arrow, 0, Qt.AlignRight | Qt.AlignVCenter)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            QDesktopServices.openUrl(QUrl(self._url))
        super().mouseReleaseEvent(ev)


RACEROOM_COMPETITIONS_URL = "https://game.raceroomracing.com/competitions/"


class SettingsWindow(QWidget):
    """0.5.4.0: Einstellungen in eigenem Fenster - App-Konfiguration, aus dem
    frueher ueberladenen 'Mehr'-Menue herausgeloest."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setWindowTitle("Einstellungen – PitBoss R3E")
        self.resize(540, 760)
        lay = QVBoxLayout(self)
        title = QLabel("App-Einstellungen")
        title.setStyleSheet("font-size:16px; font-weight:700;")
        lay.addWidget(title)

        def row(text, slot, tip=""):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        row("Design: Hell / Dunkel umschalten", self.main.toggle_theme)
        row("System-Log ein- / ausblenden", self.main.toggle_log)
        lay.addSpacing(10)
        row("Bremsmodell kalibrieren …", self.main.calibrate_brake_model,
            "Schwellwerte des Bremsmodells an echten Daten nachziehen.")
        row("Nach Updates suchen …", self.main._check_updates)
        lay.addSpacing(10)
        self._build_ai_section(lay)
        lay.addStretch(1)
        hint = QLabel("Overlay-Design (transparent / dunkel / hell) liegt weiterhin im Overlays-Menü.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#8a97a8;")
        lay.addWidget(hint)
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.close)
        lay.addWidget(btn_close)

    """Methoden des KI-Abschnitts; unten an SettingsWindow gehaengt (haelt die Klasse lesbar)."""

    def _build_ai_section(self, lay):
        grp = QGroupBox("KI-Coach (optional)")
        g = QVBoxLayout(grp)
        info = QLabel("Der Live-Coach funktioniert immer lokal. Mit einem Anbieter formuliert die KI "
                      "den Hinweis nach jeder Runde zu einem kurzen Funkspruch um. Gesendet werden nur "
                      "Rundennummer, Delta und der Hinweistext \u2013 keine Rohdaten, keine Namen. "
                      "Bei Fehlern oder ohne Netz bleibt der lokale Satz.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#8a97a8;")
        g.addWidget(info)

        self._ai_cfg = {"provider": self.main.ai_cfg.get("provider", ai_providers.LOCAL_ID),
                        "keys": dict(self.main.ai_cfg.get("keys") or {}),
                        "models": dict(self.main.ai_cfg.get("models") or {})}
        self._ai_loading = False

        row = QHBoxLayout()
        row.addWidget(QLabel("Anbieter"))
        self.ai_provider = QComboBox()
        self.ai_provider.addItem(ai_providers.LOCAL_LABEL, ai_providers.LOCAL_ID)
        for pid, spec in ai_providers.PROVIDERS.items():
            self.ai_provider.addItem(spec["label"], pid)
        row.addWidget(self.ai_provider, 1)
        g.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("API-Key"))
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setPlaceholderText("Key hier einf\u00fcgen")
        row.addWidget(self.ai_key, 1)
        self.ai_show = QPushButton("Zeigen")
        self.ai_show.setCheckable(True)
        self.ai_show.toggled.connect(lambda on: self.ai_key.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        row.addWidget(self.ai_show)
        g.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Modell"))
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        row.addWidget(self.ai_model, 1)
        g.addLayout(row)

        row = QHBoxLayout()
        self.ai_keylink = QPushButton("Key besorgen \u2026")
        self.ai_keylink.clicked.connect(self._ai_open_keypage)
        row.addWidget(self.ai_keylink)
        self.ai_test = QPushButton("Verbindung testen")
        self.ai_test.clicked.connect(self._ai_test)
        row.addWidget(self.ai_test)
        g.addLayout(row)

        self.ai_result = QLabel("")
        self.ai_result.setWordWrap(True)
        g.addWidget(self.ai_result)

        self.ai_save = QPushButton("KI-Einstellungen speichern")
        self.ai_save.clicked.connect(self._ai_save)
        g.addWidget(self.ai_save)

        note = QLabel("Der Key wird lokal gespeichert (unter Windows mit dem Benutzerkonto verschl\u00fcsselt). "
                      "Kosten tragen bei dir; bei einer Anfrage pro Runde sind sie minimal.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8;")
        g.addWidget(note)
        lay.addWidget(grp)

        self.ai_provider.currentIndexChanged.connect(self._ai_provider_changed)
        idx = max(0, self.ai_provider.findData(self._ai_cfg["provider"]))
        self.ai_provider.setCurrentIndex(idx)
        self._ai_provider_changed()

    def _ai_pid(self):
        return self.ai_provider.currentData()

    def _ai_remember_fields(self):
        """Eingaben des aktuell angezeigten Anbieters im lokalen Entwurf merken."""
        pid = getattr(self, "_ai_shown", None)
        if pid in ai_providers.PROVIDERS:
            self._ai_cfg["keys"][pid] = self.ai_key.text().strip()
            self._ai_cfg["models"][pid] = self.ai_model.currentText().strip()

    def _ai_provider_changed(self, *_):
        self._ai_remember_fields()
        pid = self._ai_pid()
        self._ai_shown = pid
        on = pid in ai_providers.PROVIDERS
        for w in (self.ai_key, self.ai_show, self.ai_model, self.ai_keylink, self.ai_test):
            w.setEnabled(on)
        self.ai_model.clear()
        self.ai_key.clear()
        if on:
            spec = ai_providers.PROVIDERS[pid]
            self.ai_model.addItems(spec["models"])
            self.ai_model.setCurrentText(self._ai_cfg["models"].get(pid) or spec["model"])
            self.ai_key.setText(self._ai_cfg["keys"].get(pid, ""))
        self.ai_result.setText("")

    def _ai_draft(self):
        self._ai_remember_fields()
        cfg = dict(self._ai_cfg)
        cfg["provider"] = self._ai_pid()
        return cfg

    def _ai_open_keypage(self):
        pid = self._ai_pid()
        if pid in ai_providers.PROVIDERS:
            QDesktopServices.openUrl(QUrl(ai_providers.PROVIDERS[pid]["key_url"]))

    def _ai_test(self):
        cfg = self._ai_draft()
        if not ai_providers.is_active(cfg):
            self.ai_result.setStyleSheet("color:#e8a33a;")
            self.ai_result.setText("Bitte zuerst einen API-Key eintragen.")
            return
        self.ai_test.setEnabled(False)
        self.ai_result.setStyleSheet("color:#8a97a8;")
        self.ai_result.setText("Teste \u2026")
        self._ai_tester = AITestWorker(cfg, self)

        def done(text, err):
            self.ai_test.setEnabled(self._ai_pid() in ai_providers.PROVIDERS)
            if err:
                self.ai_result.setStyleSheet("color:#e8212b;")
                self.ai_result.setText("Fehler: " + err)
            else:
                self.ai_result.setStyleSheet("color:#3fb950;")
                self.ai_result.setText("OK \u2013 Beispiel-Funkspruch: \u201e" + text + "\u201c")

        self._ai_tester.done.connect(done)
        self._ai_tester.start()

    def _ai_save(self):
        cfg = self._ai_draft()
        if cfg["provider"] in ai_providers.PROVIDERS and not cfg["keys"].get(cfg["provider"]):
            self.ai_result.setStyleSheet("color:#e8a33a;")
            self.ai_result.setText("Ohne API-Key bleibt der Coach lokal.")
        else:
            self.ai_result.setStyleSheet("color:#3fb950;")
            self.ai_result.setText("Gespeichert.")
        self.main.set_ai_config(cfg)


class SectorTracker:
    """0.4.9.0: echte Sektorzeiten des Spiels (mLastSector1/2, lap_time_previous_self).
    Bisher nutzte die App nur eigene 50-m-Segmente. Hier kommen die offiziellen
    S1/S2/S3 dazu, inklusive Bestsektoren und theoretischer Bestrunde."""

    def __init__(self):
        self.last = [0.0, 0.0, 0.0]
        self.best = [0.0, 0.0, 0.0]
        self.best_lap = 0.0
        self._seen_lap = None

    @staticmethod
    def _split(s1_cum, s2_cum, lap):
        """RaceRoom liefert S2 kumuliert (S1+S2). Auf Einzelsektoren umrechnen."""
        if s1_cum <= 0 or s2_cum <= 0 or lap <= 0 or s2_cum <= s1_cum or lap <= s2_cum:
            return None
        return [s1_cum, s2_cum - s1_cum, lap - s2_cum]

    def on_sample(self, s):
        """Gibt die Sektoren der gerade beendeten Runde zurueck oder None."""
        lap_no = int(getattr(s, "lap_number", 0) or 0)
        if self._seen_lap is None:
            self._seen_lap = lap_no
            return None
        if lap_no == self._seen_lap:
            return None
        self._seen_lap = lap_no
        secs = self._split(float(getattr(s, "last_sector1_s", 0.0) or 0.0),
                           float(getattr(s, "last_sector2_s", 0.0) or 0.0),
                           float(getattr(s, "last_lap_time", 0.0) or 0.0))
        if secs is None:
            return None
        self.last = secs
        for i, v in enumerate(secs):
            if v > 0 and (self.best[i] <= 0 or v < self.best[i]):
                self.best[i] = v
        lap_t = sum(secs)
        if self.best_lap <= 0 or lap_t < self.best_lap:
            self.best_lap = lap_t
        return secs

    def theoretical_best(self):
        return sum(self.best) if all(v > 0 for v in self.best) else 0.0


class BlindSpotOverlayWindow(OverlayStyleMixin, QWidget):
    """0.5.9.13: Toter-Winkel-Warnung. Zwei Anzeigen LINKS/RECHTS leuchten
    bernsteinfarben, sobald ein Auto seitlich im toten Winkel ist. Das Shared
    Memory liefert KEINE Fahrzeug-Orientierung -> die Fahrtrichtung wird aus der
    Positionsaenderung abgeleitet (geglaettet). Falls links/rechts vertauscht
    sind: 'Toter Winkel: Seiten spiegeln' im Overlay-Menue."""
    MAX_DIST = 12.0    # m: weiter entfernte Autos ignorieren
    FWD_MAX = 6.0      # m: |Laengsversatz| (etwa neben mir, vorn bis hinten)
    LAT_MIN = 1.0      # m: naeher = eigenes Auto / direkt daneben
    LAT_MAX = 5.5      # m: weiter = Nachbarspur, kein toter Winkel
    AMBER = QColor("#f5a623")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Toter-Winkel Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(360, 120)
        self.setMinimumSize(240, 96)
        self._left = False
        self._right = False
        self._prev = None
        self._hx = 0.0
        self._hz = 0.0
        self._flip = self._load_flip()
        self._drag = None

    @staticmethod
    def _load_flip():
        try:
            if BLINDSPOT_CONFIG_PATH.exists():
                return bool(json.loads(BLINDSPOT_CONFIG_PATH.read_text(encoding="utf-8")).get("flip", True))
        except Exception:
            pass
        return True  # 0.5.9.16: an echter Runde validiert - ungefippt war seitenverkehrt

    def set_flip(self, on):
        self._flip = bool(on)
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            BLINDSPOT_CONFIG_PATH.write_text(json.dumps({"flip": self._flip}), encoding="utf-8")
        except Exception:
            pass
        self.update()

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        self._compute(s)
        self.update()

    def _compute(self, s):
        self._left = self._right = False
        if s is None:
            return
        px = float(getattr(s, "pos_x", 0.0) or 0.0)
        pz = float(getattr(s, "pos_z", 0.0) or 0.0)
        spd = float(getattr(s, "speed_kmh", 0.0) or 0.0)
        # Fahrtrichtung aus Positionsdelta (nur in Bewegung), exponentiell geglaettet
        if self._prev is not None:
            dx = px - self._prev[0]
            dz = pz - self._prev[1]
            d = (dx * dx + dz * dz) ** 0.5
            if d > 0.25 and spd > 12.0:
                a = 0.35
                self._hx = (1 - a) * self._hx + a * (dx / d)
                self._hz = (1 - a) * self._hz + a * (dz / d)
        self._prev = (px, pz)
        hlen = (self._hx * self._hx + self._hz * self._hz) ** 0.5
        if hlen < 1e-3:
            return
        hx, hz = self._hx / hlen, self._hz / hlen
        for opp in (getattr(s, "opponents", ()) or ()):
            try:
                ox, oz, in_pits = float(opp[1]), float(opp[2]), bool(opp[3])
            except Exception:
                continue
            if in_pits:
                continue
            relx = ox - px
            relz = oz - pz
            dist = (relx * relx + relz * relz) ** 0.5
            if dist < 0.5 or dist > self.MAX_DIST:
                continue
            fwd = relx * hx + relz * hz          # Laengsversatz (+ vor mir)
            cross = relx * hz - relz * hx         # Seitenversatz (Vorzeichen = Seite)
            lat = abs(cross)
            if abs(fwd) > self.FWD_MAX or lat < self.LAT_MIN or lat > self.LAT_MAX:
                continue
            left = cross > 0
            if self._flip:
                left = not left
            if left:
                self._left = True
            else:
                self._right = True

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def _indicator(self, p, x, y, sq, active, label):
        fill = QColor(self.AMBER) if active else self._panel()
        if not active:
            fill.setAlpha(90)
        # Ecken-Rahmen
        p.setPen(QPen(self._faint(90) if not active else QColor(self.AMBER), 2))
        p.setBrush(Qt.NoBrush)
        cl = max(8, sq * 0.28)
        for (ex, ey, dx1, dy1, dx2, dy2) in (
            (x, y, cl, 0, 0, cl),
            (x + sq, y, -cl, 0, 0, cl),
            (x, y + sq, cl, 0, 0, -cl),
            (x + sq, y + sq, -cl, 0, 0, -cl),
        ):
            p.drawLine(QPointF(ex, ey), QPointF(ex + dx1, ey + dy1))
            p.drawLine(QPointF(ex, ey), QPointF(ex + dx2, ey + dy2))
        # Fuellung
        inset = sq * 0.16
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(x + inset, y + inset, sq - 2 * inset, sq - 2 * inset),
                          (sq - 2 * inset) * 0.3, (sq - 2 * inset) * 0.3)
        # Beschriftung oben/unten
        p.setFont(QFont("Segoe UI", 7, QFont.DemiBold))
        p.setPen(self._muted())
        p.drawText(QRectF(x - 6, y - 15, sq + 12, 12), Qt.AlignCenter, "BLIND SPOT")
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(self._muted())
        p.drawText(QRectF(x - 6, y + sq + 3, sq + 12, 12), Qt.AlignCenter, label)

    def paintEvent(self, _):
        p = self._begin_paint()
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        sq = min(h - 34, (w - 36) / 2)
        sq = max(24, sq)
        cy = (h - sq) / 2 + 3
        self._indicator(p, 14, cy, sq, self._left, "LEFT")
        self._indicator(p, w - 14 - sq, cy, sq, self._right, "RIGHT")
        p.end()


class BrakeWearModel:
    """0.4.9.2: Schaetzung der Bremsbelastung, weil RaceRoom keinen Verschleisskanal
    ausgibt (die Physik kennt ihn, Studio 397 schreibt ihn nicht in den Telemetrie-
    Buffer). Zwei unabhaengige Groessen werden ueber die Zeit integriert:

      1. Thermischer Stress  =  Integral( max(T_Bremse - T_opt, 0) ) dt   [Grad C * s]
         Reale Einheit, keine Annahme ausser der Schwelle T_opt.

      2. Reibarbeit (Index)  =  Integral( Bremsdruck * Geschwindigkeit ) dt
         Proportional zu Integral(F * v) dt. Die absolute Bremskraft ist nicht
         bekannt (mBrakePressure ist 0..1), deshalb ein relativer Index, keine Joule.

    Daraus wird ein Belag-Verschleiss in Prozent geschaetzt. Die beiden
    Referenzwerte dafuer sind Kalibrierwerte, keine Messwerte - sie liegen in
    exports/brake_model.json und koennen nach einem echten Stint angepasst werden.
    Die Prozentzahl ist also ein Modell, kein Sim-Wert."""

    DEFAULTS = {
        "t_opt_c": 500.0,        # ab hier zaehlt Hitze als Stress
        "t_fade_c": 700.0,       # ab hier Fading-Warnung
        "friction_ref": 60000.0, # Reibarbeits-Index fuer 100 % Belagverschleiss
        "thermal_ref": 600000.0, # thermischer Stress (Grad C * s) fuer 100 %
    }

    def __init__(self, config_path=None):
        self.cfg = dict(self.DEFAULTS)
        self.config_path = config_path
        self.load()
        self.thermal = [0.0, 0.0, 0.0, 0.0]   # Grad C * s je Rad
        self.friction = [0.0, 0.0, 0.0, 0.0]  # Index je Rad
        self.peak_c = [0.0, 0.0, 0.0, 0.0]
        self._last_t = None
        self._veh = None
        self._unit_min = None

    def load(self):
        if not self.config_path:
            return
        try:
            import json
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in self.DEFAULTS:
                if k in data:
                    self.cfg[k] = float(data[k])
        except Exception:
            pass

    def save(self):
        if not self.config_path:
            return
        try:
            import json
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception:
            pass

    def reset(self):
        self.thermal = [0.0, 0.0, 0.0, 0.0]
        self.friction = [0.0, 0.0, 0.0, 0.0]
        self.peak_c = [0.0, 0.0, 0.0, 0.0]
        self._last_t = None

    def _to_c(self, v):
        """RaceRoom meldet Bremstemperaturen bereits in Grad Celsius."""
        if v <= 1.0:
            return None
        return v

    def temps_c(self):
        return [self._to_c(v) for v in self._raw_last] if hasattr(self, "_raw_last") else [None] * 4

    def update(self, s):
        """Pro Telemetrie-Tick aufrufen. Laeuft unabhaengig davon, ob das
        Overlay offen ist - sonst gingen Werte beim Schliessen verloren."""
        if s is None:
            return
        try:
            import time as _t
            now = _t.monotonic()
        except Exception:
            return
        veh = str(getattr(s, "vehicle_name", "") or "")
        if veh != self._veh:
            self._veh = veh
            self.reset()
        raw = [float(getattr(s, f"brake_{k}_temp_raw", 0.0) or 0.0) for k in ("fl", "fr", "rl", "rr")]
        self._raw_last = raw
        vals = [v for v in raw if v > 1.0]
        if vals:
            m = min(vals)
            self._unit_min = m if self._unit_min is None else min(self._unit_min, m)
        if self._last_t is None:
            self._last_t = now
            return
        dt = now - self._last_t
        self._last_t = now
        if dt <= 0 or dt > 1.0:      # Pause/Hänger nicht mitzaehlen
            return
        if bool(getattr(s, "in_pits", False)):
            return
        v_ms = float(getattr(s, "speed_kmh", 0.0) or 0.0) / 3.6
        press = [float(getattr(s, f"brake_{k}_pressure", 0.0) or 0.0) for k in ("fl", "fr", "rl", "rr")]
        t_opt = float(self.cfg["t_opt_c"])
        for i in range(4):
            c = self._to_c(raw[i])
            if c is not None:
                if c > self.peak_c[i]:
                    self.peak_c[i] = c
                over = c - t_opt
                if over > 0:
                    self.thermal[i] += over * dt
            p = press[i]
            if p > 0.02 and v_ms > 1.0:
                self.friction[i] += p * v_ms * dt

    def wear_pct(self, i):
        fr = float(self.cfg["friction_ref"]) or 1.0
        th = float(self.cfg["thermal_ref"]) or 1.0
        return max(0.0, min(999.0, (self.friction[i] / fr + self.thermal[i] / th) * 100.0))

    def worst_wear(self):
        return max(self.wear_pct(i) for i in range(4))

    def fading_risk(self):
        """True, wenn ein Rad aktuell ueber der Fading-Schwelle liegt."""
        temps = self.temps_c()
        f = float(self.cfg["t_fade_c"])
        return any(c is not None and c >= f for c in temps)

    def calibrate_to(self, pct):
        """Skaliert die Referenzen so, dass der aktuelle Zustand pct Prozent
        entspricht - damit laesst sich das Modell nach einem echten Stint
        an das tatsaechliche Verhalten anpassen."""
        if pct <= 0:
            return False
        cur = self.worst_wear()
        if cur <= 0.01:
            return False
        factor = cur / float(pct)
        self.cfg["friction_ref"] = float(self.cfg["friction_ref"]) * factor
        self.cfg["thermal_ref"] = float(self.cfg["thermal_ref"]) * factor
        self.save()
        return True


class BrakeTempOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.9.0/0.4.9.2: Bremsscheibentemperaturen je Rad (brake_temp) plus
    geschaetzter Belagverschleiss aus dem BrakeWearModel (thermischer Stress +
    Reibarbeit), weil RaceRoom keinen Verschleisskanal ausgibt. Die Prozentzahl ist ein
    Modellwert - Doppelklick setzt die Stint-Werte zurueck."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Bremstemperatur Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(244, 210)
        self.setMinimumSize(200, 180)
        self._raw = [0.0, 0.0, 0.0, 0.0]
        self._model = None   # 0.4.9.2
        self._bias = 0.0
        self._press = 0.0
        self._min_seen = None
        self._live = False
        self._drag = None

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if not s:
            self._live = False; self.update(); return
        self._raw = [float(getattr(s, f"brake_{k}_temp_raw", 0.0) or 0.0) for k in ("fl", "fr", "rl", "rr")]
        self._model = getattr(main, "brake_model", None)  # 0.4.9.2
        self._bias = float(getattr(s, "rear_brake_bias", 0.0) or 0.0)
        self._press = max(float(getattr(s, f"brake_{k}_pressure", 0.0) or 0.0) for k in ("fl", "fr", "rl", "rr"))
        vals = [v for v in self._raw if v > 1.0]
        if vals:
            m = min(vals)
            self._min_seen = m if self._min_seen is None else min(self._min_seen, m)
        self._live = bool(vals)
        self.update()

    def mouseDoubleClickEvent(self, ev):   # 0.4.9.2
        if self._model is not None:
            self._model.reset()
        self.update()

    def _to_c(self, v):
        if v <= 1.0:
            return None
        return v

    def _col(self, c):   # 0.4.9.2: war @staticmethod und rief self._muted() -> NameError
        if c is None:
            return self._muted()
        if c < 150:
            return QColor("#58a6ff")     # kalt
        if c < 350:
            return QColor("#3fb950")     # Arbeitsfenster
        if c < 600:
            return QColor("#e3b341")
        return QColor("#f85149")         # ueberhitzt

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft(); ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag); ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
        self._draw_title(p, QRectF(10, 6, w - 20, 16), "BREMSEN \u00b0C")
        if not self._live:
            p.setPen(self._muted())
            p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "keine Bremstemperatur")
            p.end(); return
        pad = 12; top = 28
        cw = (w - 3 * pad) / 2.0
        ch = (h - top - pad - 14) / 2.0
        labels = ["VL", "VR", "HL", "HR"]
        for i in range(4):
            r = i // 2; c = i % 2
            x = pad + c * (cw + pad); y = top + r * (ch + 8)
            cval = self._to_c(self._raw[i])
            col = self._col(cval)
            p.setPen(QPen(self._border(), 1)); p.setBrush(self._panel())
            p.drawRoundedRect(QRectF(x, y, cw, ch), 7, 7)
            fl = QFont(); fl.setPointSize(8); p.setFont(fl); p.setPen(self._muted())
            p.drawText(QRectF(x + 6, y + 3, cw - 12, 12), Qt.AlignLeft, labels[i])
            fv = QFont(); fv.setPointSize(13); fv.setBold(True); p.setFont(fv); p.setPen(col)
            p.drawText(QRectF(x, y + 10, cw, ch - 26), Qt.AlignCenter,
                       "\u2014" if cval is None else f"{cval:.0f}")
            # Verschleiss je Rad (Modell-Schaetzung, RaceRoom liefert keinen Verschleisskanal)
            if self._model is not None:
                wpct = self._model.wear_pct(i)
                wcol = QColor("#f85149") if wpct >= 85 else QColor("#e3b341") if wpct >= 60 else QColor("#3fb950")
                bw2 = cw - 12
                p.setPen(Qt.NoPen); p.setBrush(self._trackcol())
                p.drawRoundedRect(QRectF(x + 6, y + ch - 14, bw2, 5), 2, 2)
                p.setBrush(wcol)
                p.drawRoundedRect(QRectF(x + 6, y + ch - 14, max(bw2 * min(wpct / 100.0, 1.0), 2), 5), 2, 2)
                fw2 = QFont(); fw2.setPointSize(8); p.setFont(fw2); p.setPen(wcol)
                p.drawText(QRectF(x, y + ch - 26, cw - 6, 12), Qt.AlignRight, f"{wpct:.0f} %")
        fn = QFont(); fn.setPointSize(7); p.setFont(fn); p.setPen(self._muted())
        unit = "\u00b0C"
        # 0.4.9.1: Bremsbalance + Druck; Verschleiss existiert im Shared Memory nicht
        p.drawText(QRectF(0, h - 28, w, 12), Qt.AlignCenter,
                   f"{unit}  \u00b7  Balance hinten {self._bias * 100:.0f} %  \u00b7  Druck {self._press * 100:.0f} %")
        if self._model is not None:
            m = self._model
            fade = m.fading_risk()
            fl2 = QFont(); fl2.setPointSize(8); fl2.setBold(fade); p.setFont(fl2)
            p.setPen(QColor("#f85149") if fade else self._muted())
            hot = max([c for c in m.temps_c() if c is not None] or [0.0])
            p.drawText(QRectF(0, h - 15, w, 13), Qt.AlignCenter,
                       ("FADING-GEFAHR \u00b7 " if fade else "")
                       + "Verschlei\u00df gesch\u00e4tzt"
                       + f" \u00b7 Peak {hot:.0f} \u00b0C")
        p.end()


class FuelOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.9.0: Kraftstoff - Inhalt in Litern und Prozent, Kapazitaet, Verbrauch
    der letzten Runde, Schnitt und Reichweite in Runden. Bei Hypercars zusaetzlich
    die virtuelle Energie (mVirtualEnergy)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Sprit Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(238, 158)
        self.setMinimumSize(190, 130)
        self.fuel = 0.0
        self.cap = 0.0
        self.venergy = 0.0
        self.last_use = 0.0
        self.avg_use = 0.0
        self._uses = []
        self._lap = None
        self._fuel_at_lap = None
        self._live = False
        self._drag = None

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if not s:
            self._live = False; self.update(); return
        self.fuel = float(getattr(s, "fuel_l", 0.0) or 0.0)
        self.cap = float(getattr(s, "fuel_capacity_l", 0.0) or 0.0)
        self.venergy = float(getattr(s, "virtual_energy", 0.0) or 0.0)
        lap = int(getattr(s, "lap_number", 0) or 0)
        if self._lap is None:
            self._lap = lap; self._fuel_at_lap = self.fuel
        elif lap != self._lap:
            if self._fuel_at_lap is not None:
                used = self._fuel_at_lap - self.fuel
                if 0.05 < used < 30.0 and not bool(getattr(s, "in_pits", False)):
                    self.last_use = used
                    self._uses.append(used)
                    if len(self._uses) > 5:
                        del self._uses[0:len(self._uses) - 5]
                    self.avg_use = sum(self._uses) / len(self._uses)
            self._lap = lap; self._fuel_at_lap = self.fuel
        self._live = True
        self.update()

    def laps_left(self):
        base = self.avg_use or self.last_use
        return (self.fuel / base) if base > 0.01 else None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft(); ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag); ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
        self._draw_title(p, QRectF(10, 6, w - 20, 16), "KRAFTSTOFF")
        if not self._live:
            p.setPen(self._muted()); p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "warte auf Telemetrie")
            p.end(); return
        pct = (self.fuel / self.cap) if self.cap > 0.1 else 0.0
        col = QColor("#f85149") if pct < 0.10 else QColor("#e3b341") if pct < 0.25 else QColor("#3fb950")
        fv = QFont(); fv.setPointSize(19); fv.setBold(True); p.setFont(fv); p.setPen(col)
        p.drawText(QRectF(10, 24, w - 20, 26), Qt.AlignLeft, f"{self.fuel:.1f} l")
        fs = QFont(); fs.setPointSize(10); p.setFont(fs); p.setPen(self._muted())
        p.drawText(QRectF(10, 26, w - 20, 24), Qt.AlignRight,
                   f"{pct * 100:.0f} %  von {self.cap:.0f} l" if self.cap > 0.1 else "Kapazit\u00e4t \u2014")
        # Balken
        bx, by, bw, bh = 10, 54, w - 20, 10
        p.setPen(Qt.NoPen); p.setBrush(self._trackcol()); p.drawRoundedRect(QRectF(bx, by, bw, bh), 5, 5)
        p.setBrush(col); p.drawRoundedRect(QRectF(bx, by, max(bw * min(pct, 1.0), 3), bh), 5, 5)

        def row(y, label, value, color=None):
            self._kv_row(p, w, y, label, value, color)

        row(72, "letzte Runde", f"{self.last_use:.2f} l" if self.last_use > 0 else "\u2014")
        row(92, "\u00d8 (5 Runden)", f"{self.avg_use:.2f} l" if self.avg_use > 0 else "\u2014")
        ll = self.laps_left()
        row(112, "Reichweite", f"{ll:.1f} Runden" if ll else "\u2014",
            QColor("#f85149") if (ll is not None and ll < 2) else self._fg())
        if self.venergy > 0.0001:
            row(132, "Virt. Energie", f"{self.venergy * 100:.0f} %", QColor("#58a6ff"))
        p.end()


class FFBOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.9.0: Force-Feedback-Monitor. Zeigt den Rohwert aus dem Shared Memory
    (generic.FFBTorque) als Balken um die Mitte, dazu Peak-Hold und eine
    Clipping-Anzeige. Clipping = Betrag am oberen Anschlag: dann geht Detail
    verloren und der FFB-Gain sollte runter. Zusaetzlich das physikalische
    Lenkmoment (mSteeringShaftTorque) als Referenz."""

    HISTORY = 160
    CLIP_AT = 0.985

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E FFB Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(268, 150)
        self.setMinimumSize(200, 120)
        self._hist = []
        self.val = 0.0
        self.peak = 0.0
        self.shaft = 0.0
        self.clip_frames = 0
        self.total_frames = 0
        self._seen = False
        self._drag = None

    def reset_stats(self):
        self.peak = 0.0; self.clip_frames = 0; self.total_frames = 0; self._hist = []

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if not s:
            self.update(); return
        v = float(getattr(s, "ffb_torque", 0.0) or 0.0)
        self.val = v
        self.shaft = float(getattr(s, "steering_shaft_torque", 0.0) or 0.0)
        if abs(v) > 1e-6:
            self._seen = True
        a = abs(v)
        if a > self.peak:
            self.peak = a
        self.total_frames += 1
        if a >= self.CLIP_AT:
            self.clip_frames += 1
        self._hist.append(v)
        if len(self._hist) > self.HISTORY:
            del self._hist[0:len(self._hist) - self.HISTORY]
        self.update()

    def clip_pct(self):
        return (self.clip_frames / self.total_frames * 100.0) if self.total_frames else 0.0

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft(); ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag); ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        self.reset_stats(); self.update()

    def paintEvent(self, _):
        p = self._begin_paint(); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self._lw(), self._lh()
        self._paint_frame(p, w, h)
        f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
        self._draw_title(p, QRectF(10, 6, w - 20, 16), "FORCE FEEDBACK")
        if not self._seen and self.total_frames > 30:
            p.setPen(self._muted())
            p.drawText(QRectF(0, h / 2 - 10, w, 20), Qt.AlignCenter, "kein FFBTorque-Kanal")
            p.end(); return
        a = abs(self.val)
        clipping = a >= self.CLIP_AT
        col = QColor("#f85149") if clipping else QColor("#e3b341") if a > 0.85 else QColor("#3fb950")
        # Balken um die Mitte
        bx, by, bw, bh = 12, 30, w - 24, 20
        cx = bx + bw / 2.0
        p.setPen(Qt.NoPen); p.setBrush(self._trackcol()); p.drawRoundedRect(QRectF(bx, by, bw, bh), 5, 5)
        half = (bw / 2.0) * min(a, 1.0)
        if self.val >= 0:
            p.setBrush(col); p.drawRect(QRectF(cx, by, max(half, 1.0), bh))
        else:
            p.setBrush(col); p.drawRect(QRectF(cx - max(half, 1.0), by, max(half, 1.0), bh))
        # Peak-Marker
        p.setPen(QPen(QColor("#58a6ff"), 2))
        px = (bw / 2.0) * min(self.peak, 1.0)
        p.drawLine(QPointF(cx + px, by), QPointF(cx + px, by + bh))
        p.drawLine(QPointF(cx - px, by), QPointF(cx - px, by + bh))
        p.setPen(QPen(self._faint(60), 1)); p.drawLine(QPointF(cx, by), QPointF(cx, by + bh))
        # Verlauf
        gy, gh = by + bh + 8, 34
        if len(self._hist) > 1:
            path = QPainterPath()
            step = (w - 24) / (self.HISTORY - 1)
            start = self.HISTORY - len(self._hist)
            for i, v in enumerate(self._hist):
                x = 12 + (start + i) * step
                y = gy + gh / 2.0 - max(-1.0, min(1.0, v)) * (gh / 2.0 - 1)
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            p.setPen(QPen(QColor(120, 200, 255, 150), 1)); p.setBrush(Qt.NoBrush); p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(QPointF(12, gy + gh / 2.0), QPointF(w - 12, gy + gh / 2.0))
        # Werte
        fv = QFont(); fv.setPointSize(13); fv.setBold(True); p.setFont(fv); p.setPen(col)
        p.drawText(QRectF(10, h - 40, w - 20, 20), Qt.AlignLeft, f"{self.val:+.2f}")
        fs = QFont(); fs.setPointSize(9); p.setFont(fs)
        p.setPen(QColor("#f85149") if self.clip_pct() > 1.0 else self._muted())
        p.drawText(QRectF(10, h - 40, w - 20, 20), Qt.AlignRight,
                   ("CLIPPING  " if clipping else "") + f"Clip {self.clip_pct():.1f} %")
        fn = QFont(); fn.setPointSize(8); p.setFont(fn); p.setPen(self._muted())
        p.drawText(QRectF(10, h - 20, w - 20, 14), Qt.AlignLeft,
                   f"Peak {self.peak:.2f}  \u00b7  Lenkmoment {self.shaft:.1f} Nm")
        p.end()


class LimitOverlayWindow(OverlayStyleMixin, QWidget):
    """0.4.8.7 Limit-Meter (visuell, kein Ton): Grip-Kreis aus mLocalAccel.
    Zeigt die kombinierte g-Kraft als Punkt im g-g-Diagramm und in Prozent deines
    in dieser Session gezeigten Maximums. Gruen = Luft, Rot = am Limit, Magenta =
    drueber (Rutschen/Blockieren ueber die Schlupf-Kanaele). Selbst-diagnostizierend:
    meldet, wenn der Beschleunigungskanal leer durchkommt. Doppelklick = Kalibrierung
    zuruecksetzen. Verschiebbar wie die anderen Overlays (rahmenlos, always-on-top)."""

    TRAIL = 24
    SLIP_LIMIT = 2.5      # m/s Schlupf am Patch -> "drueber"
    G_CAP = 2.3           # implausible Spitzen (Curbs) ignorieren
    CALIB_G = 1.0         # ab diesem gezeigten Max gilt % als kalibriert

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R3E Limit Overlay")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # Overlays duerfen RaceRoom nie den Fokus nehmen
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # klaut RaceRoom nicht den Fokus
        self.resize(210, 250)
        self.setMinimumSize(160, 190)
        self._lat = 0.0
        self._long = 0.0
        self._gmax = 0.0
        self._slip = 0.0
        self._trail = []
        self._live = False
        self._accel_seen = False
        self._slip_seen = False
        self._samples = 0
        self._veh = None
        self._drag = None

    def reset_calibration(self):
        self._gmax = 0.0
        self._trail = []

    def update_from_main(self, main):
        s = getattr(main, "last_live_sample", None) or (main.samples[-1] if getattr(main, "samples", None) else None)
        if not s:
            self._live = False
            self.update()
            return
        veh = getattr(s, "vehicle_name", "") or ""
        if veh != self._veh:
            self._veh = veh
            self.reset_calibration()
        lat = float(getattr(s, "accel_lat_ms2", 0.0) or 0.0) / 9.81
        lng = float(getattr(s, "accel_long_ms2", 0.0) or 0.0) / 9.81
        self._lat = lat
        self._long = lng
        self._slip = max(float(getattr(s, "tire_fl_slip_ms", 0.0) or 0.0),
                         float(getattr(s, "tire_fr_slip_ms", 0.0) or 0.0),
                         float(getattr(s, "tire_rl_slip_ms", 0.0) or 0.0),
                         float(getattr(s, "tire_rr_slip_ms", 0.0) or 0.0))
        self._samples += 1
        if abs(lat) > 1e-4 or abs(lng) > 1e-4:
            self._accel_seen = True
        if self._slip > 1e-4:
            self._slip_seen = True
        comb = (lat * lat + lng * lng) ** 0.5
        moving = (float(getattr(s, "speed_kmh", 0.0) or 0.0) > 50.0
                  and not bool(getattr(s, "in_pits", False)))
        if moving and comb <= self.G_CAP and comb > self._gmax:
            self._gmax = comb
        self._trail.append((lat, lng))
        if len(self._trail) > self.TRAIL:
            del self._trail[0:len(self._trail) - self.TRAIL]
        self._live = True
        self.update()

    def _comb(self):
        return (self._lat * self._lat + self._long * self._long) ** 0.5

    def _pct(self):
        if self._gmax < 1e-3:
            return None
        return self._comb() / self._gmax

    def _state(self):
        """(Farbe, Kurzlabel, prozenttext)"""
        if not self._accel_seen and self._samples > 30:
            return (self._muted(), "kein Accel-Kanal", "--")
        if self._slip_seen and self._slip >= self.SLIP_LIMIT:
            return (QColor("#d24bff"), "DRÜBER", self._pct_text())
        if self._gmax < self.CALIB_G:
            return (QColor("#58a6ff"), "kalibriert …", "--")
        pct = self._pct() or 0.0
        if pct < 0.85:
            return (QColor("#3fb950"), "Luft", self._pct_text())
        if pct < 0.97:
            return (QColor("#e3b341"), "nah", self._pct_text())
        return (QColor("#f85149"), "AM LIMIT", self._pct_text())

    def _pct_text(self):
        p = self._pct()
        if p is None:
            return "--"
        return f"{min(p, 1.35) * 100:.0f}%"

    # verschiebbar (rahmenlos)
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        self.reset_calibration()
        self.update()

    def paintEvent(self, _):
        p = self._begin_paint()
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self._lw()
        h = self._lh()
        # Hintergrund
        self._paint_frame(p, w, h)

        color, label, ptxt = self._state()

        # Kreis-Geometrie (oben), Text (unten)
        pad = 12
        gauge_h = h - 66
        cx = w / 2.0
        cy = pad + gauge_h / 2.0
        R = min(w - 2 * pad, gauge_h) / 2.0 - 2

        # aeusserer Grip-Kreis
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._border(), 2))
        p.drawEllipse(QPointF(cx, cy), R, R)
        # 85%- und 97%-Ringe zur Orientierung
        p.setPen(QPen(self._faint(48), 1, Qt.DashLine))
        p.drawEllipse(QPointF(cx, cy), R * 0.85, R * 0.85)
        p.drawEllipse(QPointF(cx, cy), R * 0.97, R * 0.97)
        # Fadenkreuz
        p.setPen(QPen(self._faint(52), 1))
        p.drawLine(QPointF(cx - R, cy), QPointF(cx + R, cy))
        p.drawLine(QPointF(cx, cy - R), QPointF(cx, cy + R))

        # Skala: R entspricht dem gezeigten Maximum (bzw. 1.2g bis kalibriert)
        scale = self._gmax if self._gmax >= self.CALIB_G else 1.2

        def to_pt(lat, lng):
            # lat -> x (rechts +), long -> y: Bremsen (negativ) nach unten
            x = cx + max(-1.4, min(1.4, lat / scale)) * R
            y = cy + max(-1.4, min(1.4, lng / scale)) * R
            return QPointF(x, y)

        # Trail
        if len(self._trail) > 1:
            path = QPainterPath()
            for i, (la, lo) in enumerate(self._trail):
                pt = to_pt(la, lo)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 90), 2))
            p.drawPath(path)

        # aktueller Punkt
        cur = to_pt(self._lat, self._long)
        p.setPen(QPen(self._bg(), 2))
        p.setBrush(color)
        p.drawEllipse(cur, 6, 6)

        # Prozent gross
        p.setPen(color)
        f = QFont(); f.setPointSize(20); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(0, h - 58, w, 30), Qt.AlignCenter, ptxt)
        # Label
        f2 = QFont(); f2.setPointSize(10); f2.setBold(True); p.setFont(f2)
        p.drawText(QRectF(0, h - 30, w, 16), Qt.AlignCenter, label)
        # g-Wert + gezeigtes Max klein
        f3 = QFont(); f3.setPointSize(8); p.setFont(f3)
        p.setPen(self._muted())
        info = f"{self._comb():.2f} g   ·   Max {self._gmax:.2f} g" if self._accel_seen else "warte auf Telemetrie"
        p.drawText(QRectF(0, h - 15, w, 13), Qt.AlignCenter, info)
        p.end()


class UpdateDownloadWorker(QThread):
    """0.4.8.8: laedt den Installer im Hintergrund und meldet Fortschritt."""
    progress = Signal(int, int)
    finished_result = Signal(str, str)  # (pfad, fehler)

    def __init__(self, url, dest):
        super().__init__()
        self.url = url
        self.dest = dest

    def run(self):
        try:
            updater.download_asset(self.url, self.dest,
                                   progress_cb=lambda d, t: self.progress.emit(int(d), int(t)))
            self.finished_result.emit(self.dest, "")
        except Exception as e:
            self.finished_result.emit("", str(e))


class UpdateCheckWorker(QThread):
    """Automatische Update-Pruefung beim Start im Hintergrund (blockiert die UI nicht)."""
    result = Signal(object, str)  # (info | None, fehler)

    def run(self):
        try:
            self.result.emit(updater.check_for_update(APP_VERSION), "")
        except Exception as e:
            self.result.emit(None, str(e))


class CoachAIWorker(QThread):
    """0.2.1: Eine KI-Anfrage im Hintergrund (blockiert weder UI noch Telemetrie).
    Liefert (token, text, fehler); genau eines von text/fehler ist gefuellt."""
    done = Signal(object, str, str)

    def __init__(self, cfg, facts, token, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.facts = dict(facts)
        self.token = token

    def run(self):
        try:
            self.done.emit(self.token, ai_providers.coach_line(self.cfg, self.facts), "")
        except ai_providers.AIError as e:
            self.done.emit(self.token, "", str(e))
        except Exception as e:  # nie die App wegen eines KI-Aufrufs gefaehrden
            self.done.emit(self.token, "", f"Unerwarteter Fehler: {e}")


class AITestWorker(QThread):
    """Verbindungstest aus den Einstellungen: ein Beispiel-Funkspruch."""
    done = Signal(str, str)  # (text, fehler)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)

    def run(self):
        facts = {"lap": 3, "delta_s": 0.21, "hint": "250-300 m +0.21s \u00b7 Bremsen sp\u00e4ter"}
        try:
            self.done.emit(ai_providers.coach_line(self.cfg, facts), "")
        except ai_providers.AIError as e:
            self.done.emit("", str(e))
        except Exception as e:
            self.done.emit("", f"Unerwarteter Fehler: {e}")


class LiveCoach(QObject):
    """0.4.8.4 Live-Coaching: baut bei Rundenende einen kurzen Hinweis (lokal, ohne Netz;
    optional von einer KI umformuliert) und spricht ihn per TTS *getimt auf der Geraden* aus, damit nicht
    mitten in der Kurve geredet wird. Opt-in ueber Mehr-Menue / F11.

    0.2.1: Ist in den Einstellungen ein KI-Anbieter mit Key gewaehlt, formuliert dieser den
    lokalen Hinweis im Hintergrund zu einem Funkspruch um. Der lokale Satz steht immer sofort
    bereit und wird nur ersetzt, wenn die Antwort rechtzeitig (vor dem Sprechen) kommt.

    Ablauf: on_lap_completed() setzt einen
    pending_text. maybe_speak_on_straight() wird bei jedem live_tick gerufen und
    spricht den pending_text erst, wenn das Auto schnell/gesetzt auf einer Geraden
    ist und der Cooldown abgelaufen ist. So kommt pro Runde hoechstens ein Satz.
    """

    COOLDOWN_S = 8.0            # min. Abstand zwischen zwei gesprochenen Hinweisen
    STRAIGHT_MIN_SPEED = 90.0  # km/h - "schnell & gesetzt" (auch fuer langsamere RaceRoom-Autos)
    _PLACEHOLDERS = ("aktuell ok", "Live sammelt Daten", "Referenz laden",
                     "Referenz importieren/Analyse", "Live-Vergleich aktiv", "")

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.enabled = False
        self.pending_text = None
        self.last_spoken_ts = 0.0
        self.last_lap_done = None
        self._pending_facts = {"lap": 0, "delta_s": None, "hint": ""}
        self._ai_worker = None
        self._ai_token = 0
        self.ai_last_error = ""

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not self.enabled:
            self.pending_text = None

    # ---- Rundenende -> Hinweis bauen -------------------------------------
    def on_lap_completed(self, rows, lap_number, delta_s, coach_line):
        if not self.enabled or lap_number is None:
            return
        if not self.main.tts.is_available():
            return
        if self.last_lap_done == lap_number:
            return  # eine Runde -> hoechstens eine Anfrage
        self.last_lap_done = lap_number
        facts = self._facts(lap_number, delta_s, coach_line)
        if not self._meaningful(facts):
            return  # nichts Sinnvolles zu sagen -> still bleiben
        self._pending_facts = facts
        self.pending_text = self._local_line(facts)
        self._ask_ai(facts)

    # ---- optionale KI-Umformulierung (0.2.1) -----------------------------
    def _ask_ai(self, facts):
        cfg = getattr(self.main, "ai_cfg", None)
        if not cfg or not ai_providers.is_active(cfg):
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return  # vorige Anfrage haengt noch -> lokaler Satz genuegt
        self._ai_token += 1
        w = CoachAIWorker(cfg, facts, self._ai_token, self)
        w.done.connect(self._on_ai_done)
        w.finished.connect(w.deleteLater)
        self._ai_worker = w
        w.start()

    def _on_ai_done(self, token, text, err):
        self._ai_worker = None
        if err:
            if err != self.ai_last_error:  # gleiche Fehlermeldung nicht jede Runde wiederholen
                self.main.log.append("KI-Coach: " + err + " \u2013 lokaler Hinweis wird verwendet.")
            self.ai_last_error = err
            return
        self.ai_last_error = ""
        # nur ersetzen, wenn der Satz zu genau dieser Runde noch nicht gesprochen wurde
        if token == self._ai_token and self.pending_text and self.enabled:
            self.pending_text = text

    def _facts(self, lap_number, delta_s, coach_line):
        try:
            d = float(delta_s) if delta_s is not None else None
        except Exception:
            d = None
        return {"lap": int(lap_number), "delta_s": d, "hint": (coach_line or "").strip()}

    def _meaningful(self, facts):
        if facts["hint"] not in self._PLACEHOLDERS:
            return True
        return facts["delta_s"] is not None and abs(facts["delta_s"]) >= 0.10

    def _local_line(self, facts):
        # Kurzer Satz aus Hinweis bzw. Delta, komplett lokal.
        hint = facts["hint"]
        if hint and hint not in self._PLACEHOLDERS:
            topic = hint.split("\u00b7")[-1].strip() if "\u00b7" in hint else hint
            return f"Fokus naechste Runde: {topic}."
        if facts["delta_s"] is not None and facts["delta_s"] <= -0.10:
            return "Gute Runde, genau so weiter."
        return "Sauber bleiben, Linie halten."

    # ---- Ausgabe getimt auf der Geraden ----------------------------------
    def _is_straight(self, s):
        try:
            return (float(s.throttle) >= 0.95 and float(s.brake) <= 0.03
                    and abs(float(s.steering)) <= 0.06
                    and float(s.speed_kmh) >= self.STRAIGHT_MIN_SPEED
                    and not bool(getattr(s, "in_pits", False)))
        except Exception:
            return False

    def maybe_speak_on_straight(self, s):
        if not self.enabled or not self.pending_text or s is None:
            return
        now = datetime.now().timestamp()
        if now - self.last_spoken_ts < self.COOLDOWN_S:
            return
        if not self._is_straight(s):
            return
        try:
            if self.main.tts.is_available() and self.main.tts.speak(self.pending_text, interrupt=True):
                self.last_spoken_ts = now
        finally:
            self.pending_text = None


class BrakeCoach(QObject):
    """0.4.8.6 Kurven-Coach: leitet aus DEINER Live-Bestlap pro harter Kurve drei
    Referenzpunkte ab - Bremspunkt, Einlenkpunkt, Gaspunkt - und sagt sie getimt an:
    Bremspunkt als Countdown (drei/zwei/eins/bremsen), Einlenken und Gas als kurze
    Einzel-Cues. Rein telemetriebasiert, kein Netz. Vorsynthetisierte Piper-Clips
    (latenzarm ueber winsound). Opt-in / F12. Einlenken und Gas einzeln abschaltbar.

    Bremspunkte/Cues stammen aus deiner schnellsten Live-Runde (live_best_reference_lap).
    Faellt diese Referenz weg, schweigt der Coach.
    """

    HARD_DROP_KMH = 15.0     # Mindest-Tempoabbau (zusaetzlich >= MIN_DROP_FRAC der Einfahrtgeschwindigkeit)
    MIN_DROP_FRAC = 0.12
    BRAKE_ON = 0.30          # Bremse gilt als "an" (auch leichtes Bremsen vor langsameren Kurven)
    BRAKE_OFF = 0.12         # Bremse gilt als "aus"
    MERGE_DIST_M = 25.0      # nahe Bremspunkte zusammenfassen (Schikanen bleiben getrennt)
    START_LEAD_S = 3.6       # ab hier wird ein Bremspunkt aktiv verfolgt
    BRAKE_LEAD_S = 0.70      # 0.4.9.8: Standard weiter vorgezogen (war 0.45), einstellbar
    MIN_SPEED_MPS = 12.0     # darunter kein sinnvoller Countdown (Pit/langsam)

    STEER_ON = 0.14          # 0.4.8.8: hoeher gegen Fehl-Trigger durch Lenk-Noise
    TURNIN_WINDOW_M = 160.0  # Einlenkpunkt max. so weit nach dem Bremspunkt suchen
    THROTTLE_ON = 0.55       # Gas gilt als "committed" am Ausgang
    GAS_WINDOW_M = 420.0     # Gaspunkt max. so weit nach dem Bremspunkt suchen
    CUE_ARM_S = 1.2          # ab hier wird ein Einzel-Cue (Einlenken/Gas) scharf
    TURNIN_LEAD_S = 0.45     # 0.4.8.8: Einlenken frueher ansagen
    GAS_LEAD_S = 0.40        # 0.4.8.8: Gas frueher ansagen

    CLIPS = {"3": "drei", "2": "zwei", "1": "eins", "0": "bremsen",
             "T": "einlenken", "G": "Gas"}

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.enabled = False
        self.load_timing()        # 0.4.9.8: gespeicherter Vorlauf
        self.say_turnin = True    # Einlenken-Hinweis (Menue)
        self.say_gas = True       # Gas-Hinweis (Menue)
        self.corners = []         # [{"brake","entry","drop","turnin","gas"}]
        self.events = []          # flach & sortiert: [{"dist","kind"}]
        self.ref_lap = None
        self._active = None       # dist des aktuell verfolgten Events
        self._said = set()        # angesagte Marker fuer das aktive Event

    # ---- 0.4.9.8: Vorlauf laden/setzen/speichern ------------------------
    LEAD_KEYS = {"brake": "BRAKE_LEAD_S", "turnin": "TURNIN_LEAD_S", "gas": "GAS_LEAD_S"}

    def load_timing(self):
        try:
            import json
            with open(COACH_TIMING_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for kind, attr in self.LEAD_KEYS.items():
                if kind in cfg:
                    setattr(self, attr, max(0.0, min(3.0, float(cfg[kind]))))
        except Exception:
            pass

    def get_lead(self, kind):
        return float(getattr(self, self.LEAD_KEYS.get(kind, "BRAKE_LEAD_S")))

    def set_lead(self, kind, value):
        attr = self.LEAD_KEYS.get(kind)
        if not attr:
            return False
        setattr(self, attr, max(0.0, min(3.0, float(value))))
        try:
            import json
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(COACH_TIMING_PATH, "w", encoding="utf-8") as f:
                json.dump({k: self.get_lead(k) for k in self.LEAD_KEYS}, f, indent=2)
        except Exception:
            pass
        return True

    def set_enabled(self, on):
        self.enabled = bool(on)
        self._active = None
        self._said = set()
        if self.enabled:
            try:
                self.main.tts.prewarm_clips(self.CLIPS)
            except Exception:
                pass

    def has_points(self):
        return bool(self.corners)

    # ---- Referenzpunkte aus der Bestlap extrahieren ----------------------
    def set_reference_from_rows(self, rows):
        corners = self._extract_corners(rows)
        if corners:
            self.corners = corners
            self.events = self._build_events(corners)
            self.ref_lap = getattr(self.main, "live_best_reference_lap", None)

    def _extract_corners(self, rows):
        data = []
        for r in rows:
            try:
                d = float(r.lap_dist_m)
                if d >= 0:
                    data.append((d, float(r.brake), float(r.speed_kmh),
                                 abs(float(r.steering)), float(r.throttle)))
            except Exception:
                continue
        if len(data) < 200:
            return []
        data.sort(key=lambda x: x[0])
        n = len(data)
        corners = []
        armed = True
        for i in range(1, n):
            d, b, v, st, thr = data[i]
            pb = data[i - 1][1]
            if armed and pb < self.BRAKE_ON <= b:
                entry = v
                k = i - 1
                while k >= 0 and (d - data[k][0]) < 25.0:
                    entry = max(entry, data[k][2]); k -= 1
                minv = v; m = i
                while m < n and data[m][1] > self.BRAKE_OFF and (data[m][0] - d) < 400.0:
                    minv = min(minv, data[m][2]); m += 1
                if (entry - minv) >= max(self.HARD_DROP_KMH, self.MIN_DROP_FRAC * entry):
                    corners.append({
                        "brake": d, "entry": entry, "drop": entry - minv,
                        "turnin": self._find_turnin(data, i, d),
                        "gas": self._find_gas(data, i, d),
                    })
                armed = False
            elif b < self.BRAKE_OFF:
                armed = True
        # nahe Bremspunkte zusammenfassen, staerksten behalten
        corners.sort(key=lambda c: c["brake"])
        merged = []
        for c in corners:
            if merged and (c["brake"] - merged[-1]["brake"]) < self.MERGE_DIST_M:
                if c["drop"] > merged[-1]["drop"]:
                    merged[-1] = c
            else:
                merged.append(c)
        return merged

    def _find_turnin(self, data, i, brake_dist):
        # erster nennenswerter Lenkeinschlag nach dem Bremsbeginn
        n = len(data)
        j = i
        while j < n and (data[j][0] - brake_dist) < self.TURNIN_WINDOW_M:
            if data[j][3] >= self.STEER_ON and (j + 1 >= n or data[j + 1][3] >= self.STEER_ON * 0.8):
                dd = data[j][0]
                return dd if dd > brake_dist else None
            j += 1
        return None

    def _find_gas(self, data, i, brake_dist):
        # erster Gas-Punkt am Ausgang: Bremse aus UND Gas >= THROTTLE_ON
        n = len(data)
        j = i
        brake_released = False
        while j < n and (data[j][0] - brake_dist) < self.GAS_WINDOW_M:
            if data[j][1] < self.BRAKE_OFF:
                brake_released = True
            if brake_released and data[j][4] >= self.THROTTLE_ON and (j + 1 >= n or data[j + 1][4] >= self.THROTTLE_ON):
                dd = data[j][0]
                return dd if dd > brake_dist else None
            j += 1
        return None

    def _build_events(self, corners):
        ev = []
        for c in corners:
            ev.append({"dist": c["brake"], "kind": "brake"})
            if c["turnin"] is not None:
                ev.append({"dist": c["turnin"], "kind": "turnin"})
            if c["gas"] is not None:
                ev.append({"dist": c["gas"], "kind": "gas"})
        ev.sort(key=lambda e: e["dist"])
        return ev

    def _kind_enabled(self, kind):
        if kind == "turnin":
            return self.say_turnin
        if kind == "gas":
            return self.say_gas
        return True  # brake immer

    def _next_event(self, cur_dist):
        best = None
        for e in self.events:
            if e["dist"] > cur_dist and self._kind_enabled(e["kind"]):
                if best is None or e["dist"] < best["dist"]:
                    best = e
        return best

    # ---- Ansage im live_tick ---------------------------------------------
    def update(self, s):
        if not self.enabled or not self.events or s is None:
            return
        if getattr(self.main, "live_best_reference_lap", None) is None:
            return  # Referenz weg -> still
        try:
            if bool(getattr(s, "in_pits", False)):
                self._active = None; self._said = set(); return
            # 0.4.8.8: im Training auch bei ungueltiger Runde ansagen; nur im Rennen unterdruecken
            if int(getattr(s, "session_type", 0)) >= 10 and bool(getattr(s, "lap_invalidated", False)):
                self._active = None; self._said = set(); return
            cur = float(s.lap_dist_m)
            spd = float(s.speed_kmh) / 3.6
        except Exception:
            return
        if cur < 0 or spd < self.MIN_SPEED_MPS:
            self._active = None; self._said = set(); return
        ev = self._next_event(cur)
        if ev is None:
            self._active = None; self._said = set(); return
        tt = (ev["dist"] - cur) / spd
        if self._active != ev["dist"]:
            arm = (max(self.START_LEAD_S, self.BRAKE_LEAD_S + 0.6) if ev["kind"] == "brake"
                   else max(self.CUE_ARM_S, self.get_lead(ev["kind"]) + 0.4))  # 0.4.9.8
            if tt <= arm:
                self._active = ev["dist"]; self._said = set()
            else:
                return
        if ev["kind"] == "brake":
            if tt <= self.BRAKE_LEAD_S:
                self._announce("0"); return
            for mrk in (1, 2, 3):
                if (mrk - 1) < tt <= mrk:
                    self._announce(str(mrk))
                    break
        else:
            lead = self.TURNIN_LEAD_S if ev["kind"] == "turnin" else self.GAS_LEAD_S
            if tt <= lead:
                self._announce("T" if ev["kind"] == "turnin" else "G")

    def _announce(self, key):
        if key in self._said:
            return
        self._said.add(key)
        try:
            self.main.tts.play_clip(key, self.CLIPS.get(key, ""))
        except Exception:
            pass


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PitBoss R3E – {APP_VERSION}")
        self.resize(1520, 920)
        logo_path = ASSET_DIR / "pitboss_app_icon.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))
        self.reader = R3EReader(Sample)
        self.hardware_profiles = self.load_hardware_profiles()
        self.current_profile_name = self.load_last_active_profile_name()
        self.samples: List[Sample] = []
        self.lap_summaries: List[LapSummary] = []
        self.reference_lap: Optional[LapSummary] = None
        self.compare_lap: Optional[LapSummary] = None
        self.segment_deltas = []
        self.manual_reference_lap: Optional[int] = None
        self.manual_compare_lap: Optional[int] = None
        self.external_reference = None
        self.use_external_reference = False
        self.recording = False
        self.recording_signature = None
        self.rejected_sample_count = 0
        self.overlay_window = None
        self.corner_name_overlay_window = None  # 0.2.37
        self.corner_list = []  # 0.2.37: erkannte Kurven der aktuellen Strecke
        self.corner_track = ""  # 0.2.37
        self.corner_track_len = 0.0  # 0.2.37
        self.tire_overlay_window = None
        self.pedal_overlay_window = None  # 0.4.7.1
        self.limit_overlay_window = None  # 0.4.8.7
        self.blindspot_overlay_window = None   # 0.5.9.13: Toter-Winkel-Overlay
        self.lift_coast_lap = None
        self.lift_coast_time_s = 0.0
        self.lift_coast_estimated_saved_l = 0.0
        self._lift_coast_throttle_rate = None  # EMA l/s Verbrauch unter Vollgas dieser Runde
        self._lift_coast_last_fuel_l = None
        self._lift_coast_last_ts = None
        self.brake_overlay_window = None     # 0.4.9.0
        self.fuel_overlay_window = None      # 0.4.9.0
        self.ffb_overlay_window = None       # 0.4.9.0
        self.sector_tracker = SectorTracker()  # 0.4.9.0
        self.pit_overlay_window = None       # 0.4.9.1
        self.delta_overlay_window = None
        self.laptime_overlay_window = None
        self.damage_overlay_window = None
        self.overlay_style = self.load_overlay_style()  # 0.4.9.1
        self.brake_model = BrakeWearModel(config_path=str(BRAKE_MODEL_PATH))  # 0.4.9.2
        self.damage_model = DamageModel(config_path=str(DAMAGE_MODEL_PATH))  # 0.4.9.4
        self.tts = SpeechEngine(config_path=str(EXPORT_DIR / "tts_config.json"))  # 0.4.7.2
        self.tire_overlay_autostart = True
        self._tire_overlay_autoshown = False
        self.auto_bestlap_export_enabled = True
        self.auto_switch_recording_enabled = True  # 0.5.9.24: Auto-Stop/Start bei Strecken-/Fahrzeugwechsel
        self.include_invalid_laps = bool(load_analysis_config().get("include_invalid_laps", False))  # 0.2.31
        self.pending_switch_signature = None
        self.pending_switch_count = 0
        self.auto_bestlap_export_path = None
        self.auto_bestlap_lap_number = None
        self.auto_bestlap_time_s = None
        self.auto_bestlap_live_mode = True
        self.last_record_hotkey_ts = 0.0
        self.last_overlay_hotkey_ts = 0.0
        self.last_auto_hotkey_ts = 0.0
        self.last_snapshot_hotkey_ts = 0.0
        self.last_report_save_error = ""
        self.last_csv_save_error = ""
        self.hotkey_config = load_hotkey_config()  # 0.2.5: frei belegbare Hotkeys
        self.global_hotkey_state = {k: False for k in self.hotkey_config.values()}
        self.last_tire_overlay_hotkey_ts = 0.0
        self.last_live_sample = None
        self.live_log_enabled = False  # 0.5.9.26: Live-Telemetrie-Log, unabhaengig vom Recording
        self.live_log_writer = None
        self.live_log_fh = None
        self.live_log_path = None
        self.live_log_row_count = 0
        self.live_smooth_lap_time = None  # 0.5.9.26: eigener Echtzeit-Rundentimer, s.u.
        self._live_clock_anchor_raw = None
        self._live_clock_anchor_ts = None
        self._live_clock_lap = None
        self.live_lap_number = None
        self.live_lap_samples: List[Sample] = []
        self.live_delta_s = None
        self.live_coach_line = "Referenz laden"
        self.live_coach_enabled = False  # 0.4.8.4: Live-Sprach-Coaching (opt-in)
        self.ai_cfg = ai_providers.load_config(self._ai_config_path())  # 0.2.1
        self.live_coach = LiveCoach(self)  # 0.4.8.4
        self.brake_coach_enabled = False  # 0.4.8.5: Brems-Countdown (opt-in)
        self.brake_coach = BrakeCoach(self)  # 0.4.8.5
        self.live_best_reference_segments = {}
        self.live_best_reference_lap = None
        self.live_best_reference_time_s = None
        self.live_timer = QTimer(self)
        self.live_timer.setInterval(100)
        self.live_timer.timeout.connect(self.live_tick)
        self.live_timer.start()
        self.timer = QTimer(self)
        self.timer.setInterval(100)  # 10 Hz live recorder
        self.timer.timeout.connect(self.capture_tick)

        root = QWidget(); self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self._root = root
        root.setObjectName("rootBg")
        self._theme = self._load_theme()
        self.apply_theme(self._theme)
        if os.environ.get("PITBOSS_NO_UPDATE_CHECK", "") != "1":
            QTimer.singleShot(4000, self._auto_check_updates)  # Start-Pruefung, still bei Fehler/aktuell
        # ---- 0.2.0: Kopfleiste (Logo, Verbindung, Aufnahme, Menues) -----------
        top = QFrame(); top.setObjectName("topBar"); top.setFixedHeight(62)
        top_l = QHBoxLayout(top); top_l.setContentsMargins(14, 6, 14, 6); top_l.setSpacing(10)
        logo = QLabel()
        logo_path = ASSET_DIR / "pitboss_header_logo.png"
        if logo_path.exists():
            logo.setPixmap(QPixmap(str(logo_path)).scaled(240, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))  # PitBoss + RaceRoom kombiniert
        self.brand_logo = logo
        self._style_rr_logo()
        top_l.addWidget(logo)
        top_l.addSpacing(12)
        self.conn_pill = QLabel("WARTET AUF RACEROOM")
        self.conn_pill.setObjectName("connPill"); self.conn_pill.setProperty("state", "off")
        top_l.addWidget(self.conn_pill)
        top_l.addStretch(1)
        outer.addWidget(top)

        self.btn_snapshot = QPushButton("Snapshot lesen")
        self.btn_record = QPushButton("●  AUFNAHME STARTEN")
        self.btn_record.setObjectName("recBtn")
        self.btn_stop = QPushButton("Recording stoppen")
        self.btn_report = QPushButton("Report speichern")
        self.btn_csv = QPushButton("CSV speichern")
        self.btn_clear = QPushButton("Löschen")
        self.btn_export = QPushButton("Export-Ordner öffnen")
        self.btn_ref_export = QPushButton("Referenz exportieren")
        self.btn_ref_import = QPushButton("Referenz importieren")
        self.btn_overlay = QPushButton("Monitor-Overlay")
        self.btn_tire_overlay = QPushButton("Reifen-Overlay")
        self.btn_pedal_overlay = QPushButton("Pedal-Overlay")
        self.btn_auto_bestlap = QPushButton("Auto-Bestlap: AN")
        self.btn_auto_switch = QPushButton("Auto-Wechsel: AN")
        self.btn_live_log = QPushButton("Live-Log: AUS")
        self.btn_live_log.setToolTip(
            "Zeichnet die rohe Live-Telemetrie (unabhängig vom Recording) in eine CSV – "
            "Datei liegt in Dokumente\\PitBoss R3E\\csv."
        )
        # Diese Buttons bleiben als interne Ausloeser (Hotkeys/Menues rufen click() auf), sind aber nie sichtbar.
        for _b in (self.btn_snapshot, self.btn_stop, self.btn_csv, self.btn_clear, self.btn_export,
                   self.btn_ref_export, self.btn_ref_import, self.btn_overlay, self.btn_tire_overlay,
                   self.btn_pedal_overlay, self.btn_auto_bestlap, self.btn_auto_switch, self.btn_live_log):
            _b.setVisible(False)
        # Optionale SimHub-Vergleichswerte (Debug) existieren nur noch als unsichtbare Felder.
        self.ref_speed = QLineEdit(); self.ref_gear = QLineEdit(); self.ref_fuel = QLineEdit(); self.ref_rpm = QLineEdit()
        self.ref_throttle = QLineEdit(); self.ref_brake = QLineEdit(); self.ref_steer = QLineEdit(); self.ref_trackm = QLineEdit()

        from PySide6.QtWidgets import QToolButton, QMenu
        top_l.addWidget(self.btn_record)
        top_l.addWidget(self.btn_report)
        self.btn_overlays = QToolButton()
        self.btn_overlays.setText("Overlays  ▾")
        self.btn_overlays.setPopupMode(QToolButton.InstantPopup)
        _ov = QMenu(self.btn_overlays)
        _ov.addAction("Reifen-Overlay", self.toggle_tire_overlay)
        _ov.addAction("Pedal-Overlay", self.toggle_pedal_overlay)
        _ov.addAction("Monitor-Overlay", self.toggle_overlay)
        _ov.addSeparator()
        _ov.addAction("Rundenzeiten (Delta/Prognose)", self.toggle_laptime_overlay)
        _ov.addAction("Rundenzeiten-Graph", self.toggle_lapgraph_overlay)
        _ov.addAction("Flaggen (auto bei Flagge)", self.toggle_flag_overlay)
        _ov.addAction("Überholalarm (hinten)", self.toggle_overtake_overlay)
        _ov.addAction("Abstand & Distanz", self.toggle_delta_overlay)
        _ov.addAction("Boxenstopp", self.toggle_pit_overlay)
        _ov.addAction("Fahrzeugschäden", self.toggle_damage_overlay)
        _ov.addAction("Toter Winkel", self.toggle_blindspot_overlay)
        self.act_blindspot_flip = _ov.addAction("Toter Winkel: Seiten spiegeln")
        self.act_blindspot_flip.setCheckable(True)
        self.act_blindspot_flip.setChecked(BlindSpotOverlayWindow._load_flip())
        self.act_blindspot_flip.toggled.connect(self.set_blindspot_flip)
        _ov.addAction("Bremstemperaturen (inkl. Verschleiß-Schätzung)", self.toggle_brake_overlay)
        _ov.addAction("Kraftstoff", self.toggle_fuel_overlay)
        _ov.addAction("Kurven-Namen", self.toggle_corner_name_overlay)  # 0.2.41: ins Overlays-Menue verschoben (war unter Mehr)
        _ov.addAction("Force Feedback", self.toggle_ffb_overlay)
        _ov.addAction("Limit-Meter", self.toggle_limit_overlay)
        _ov.addSeparator()
        _stylemenu = _ov.addMenu("Design aller Overlays")
        self.overlay_style_actions = {}
        for _key, _label in (("transparent", "Transparent (durchscheinend)"),
                             ("dark", "Deckend dunkel"),
                             ("light", "Deckend hell")):
            _a = _stylemenu.addAction(_label)
            _a.setCheckable(True)
            _a.setChecked(getattr(self, "overlay_style", "transparent") == _key)
            _a.triggered.connect(lambda _c=False, k=_key: self.set_overlay_style(k))
            self.overlay_style_actions[_key] = _a
        self.btn_overlays.setMenu(_ov)
        top_l.addWidget(self.btn_overlays)

        self.btn_coach = QToolButton()
        self.btn_coach.setText("Coach  ▾")
        self.btn_coach.setPopupMode(QToolButton.InstantPopup)
        _coach = QMenu(self.btn_coach)
        self.act_live_coach = _coach.addAction("Live-Coach (Sprachhinweise)")
        self.act_live_coach.setCheckable(True)
        self.act_live_coach.setChecked(self.live_coach_enabled)
        self.act_live_coach.toggled.connect(self.set_live_coach_enabled)
        _coach.addAction("KI-Anbieter f\u00fcr den Live-Coach \u2026").triggered.connect(self.open_settings_window)
        self.act_brake_coach = _coach.addAction("Kurven-Coach: Bremsen/Einlenken/Gas (F12)")
        self.act_brake_coach.setCheckable(True)
        self.act_brake_coach.setChecked(self.brake_coach_enabled)
        self.act_brake_coach.toggled.connect(self.set_brake_coach_enabled)
        self.act_cue_turnin = _coach.addAction("   • Einlenken-Hinweis")
        self.act_cue_turnin.setCheckable(True)
        self.act_cue_turnin.setChecked(self.brake_coach.say_turnin)
        self.act_cue_turnin.toggled.connect(lambda on: setattr(self.brake_coach, "say_turnin", bool(on)))
        self.act_cue_gas = _coach.addAction("   • Gas-Hinweis")
        self.act_cue_gas.setCheckable(True)
        self.act_cue_gas.setChecked(self.brake_coach.say_gas)
        self.act_cue_gas.toggled.connect(lambda on: setattr(self.brake_coach, "say_gas", bool(on)))
        _coach.addSeparator()
        _coach.addAction("Ansage-Vorlauf …", self.set_coach_lead_all)
        self.btn_coach.setMenu(_coach)
        top_l.addWidget(self.btn_coach)

        self.btn_more = QToolButton()
        self.btn_more.setText("Mehr  ▾")
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        _more = QMenu(self.btn_more)
        _more.addAction("CSV speichern", self.btn_csv.click)
        _more.addAction("Referenz exportieren", self.btn_ref_export.click)
        _more.addAction("Referenz importieren", self.btn_ref_import.click)
        _more.addSeparator()
        self.act_auto_bestlap = _more.addAction("Auto-Bestlap-Export (" + self.hotkey_config.get("auto_bestlap", "F7") + ")")
        self.act_auto_bestlap.setCheckable(True)
        self.act_auto_bestlap.triggered.connect(lambda _c=False: self.btn_auto_bestlap.click())
        self.act_auto_switch = _more.addAction("Auto-Wechsel bei Strecke/Fahrzeug")
        self.act_auto_switch.setCheckable(True)
        self.act_auto_switch.triggered.connect(lambda _c=False: self.btn_auto_switch.click())
        _more.addAction("Live-Telemetrie-Log (Debug) ein/aus", self.btn_live_log.click)
        self.act_include_invalid = _more.addAction("Ungültige Runden in Auswertung (inkl. Referenz/Vergleich)")  # 0.2.31
        self.act_include_invalid.setCheckable(True)
        self.act_include_invalid.setChecked(bool(self.include_invalid_laps))
        self.act_include_invalid.toggled.connect(self.toggle_include_invalid_laps)
        _more.addAction("Hotkeys belegen …", self.open_hotkey_settings)  # 0.2.5
        _more.addAction("Kurven benennen …", self.open_corner_name_dialog)  # 0.2.37; Overlay-Umschalter seit 0.2.41 im Overlays-Menue
        _more.addSeparator()
        _more.addAction("Beta-Feedback senden (Bug/Wunsch) …", self.open_beta_feedback)  # 0.2.33
        _more.addSeparator()
        _more.addAction("Export-Ordner öffnen", self.btn_export.click)
        _more.addAction("Aufzeichnung löschen", self.btn_clear.click)
        self.btn_more.setMenu(_more)
        top_l.addWidget(self.btn_more)

        self.btn_settings = QToolButton()
        self.btn_settings.setText("Einstellungen")
        self.btn_settings.clicked.connect(self.open_settings_window)
        top_l.addWidget(self.btn_settings)

        # ---- 0.2.2: Tab-Navigation unter der Kopfleiste im Stil des RaceRoom-Menues
        #      (aktiver Reiter weiss, die anderen dunkelgrau). Wird nach dem Anlegen der Tabs befuellt.
        navbar = QFrame(); navbar.setObjectName("navBar")
        self.nav_box = QHBoxLayout(navbar); self.nav_box.setContentsMargins(18, 12, 18, 0); self.nav_box.setSpacing(2)
        self.nav_prev = QPushButton("\u2039"); self.nav_prev.setObjectName("navArrow")
        self.nav_next = QPushButton("\u203a"); self.nav_next.setObjectName("navArrow")
        self.nav_prev.setToolTip("Vorherige Ansicht"); self.nav_next.setToolTip("N\u00e4chste Ansicht")
        self.nav_prev.clicked.connect(lambda: self.nav_step(-1))
        self.nav_next.clicked.connect(lambda: self.nav_step(+1))
        self.nav_box.addWidget(self.nav_prev); self.nav_box.addWidget(self.nav_next)
        self.nav_box.addSpacing(10)
        outer.addWidget(navbar)
        content = QWidget(); content.setProperty("plain", True)
        layout = QVBoxLayout(content); layout.setContentsMargins(18, 12, 18, 12); layout.setSpacing(6)
        outer.addWidget(content, 1)

        self.status = QLabel("Bereit. RaceRoom starten, ins Auto gehen, Aufnahme starten.")
        self.status.setObjectName("statusLine")
        layout.addWidget(self.status)

        # Setup + Fahrerprofil leben jetzt im Dashboard (Sitzungs-Leiste), werden hier nur angelegt.
        self.setup_selector = QComboBox()
        self.setup_selector.setEditable(True)
        self.setup_selector.addItems(["nicht gesetzt", "Baseline", "Race", "Quali", "Stable/Safe", "Custom"])
        self.setup_selector.setMinimumWidth(220)
        self.setup_selector.lineEdit().setPlaceholderText("Setup eintragen, z. B. Race, Quali …")
        self.setup_selector.setToolTip("Manuelle Setup-Dokumentation: erscheint im Report und Referenzexport. RaceRoom liefert den Setup-Namen nicht per Shared Memory.")
        self.btn_fahrer_hardware = QPushButton("Fahrer && Hardware")
        self.btn_fahrer_hardware.setToolTip("Zur Ansicht Fahrer & Hardware wechseln.")
        self.driver_profile_selector = QComboBox()
        self.driver_profile_selector.setEditable(True)
        self.driver_profile_selector.addItems(list(self.hardware_profiles.keys()))
        if self.current_profile_name in self.hardware_profiles:
            self.driver_profile_selector.setCurrentText(self.current_profile_name)
        self.driver_profile_selector.setMinimumWidth(200)
        self.driver_profile_selector.setToolTip("Fahrer-/Hardwareprofil wählen. Wird im Report gespeichert.")
        self.btn_profile_new = QPushButton("Profil neu")
        self.btn_profile_load = QPushButton("Profil laden")
        self.btn_profile_save = QPushButton("Profil speichern")
        self.btn_profile_delete = QPushButton("Profil löschen")
        self.btn_profile_load.setToolTip("driver_hardware_profiles.json oder ein einzelnes Profil-JSON importieren. Bestehende Profile werden nicht überschrieben.")
        self.btn_profile_menu = QToolButton()
        self.btn_profile_menu.setText("Profil  ▾")
        self.btn_profile_menu.setPopupMode(QToolButton.InstantPopup)
        _pm = QMenu(self.btn_profile_menu)
        _pm.addAction("Profil neu", self.btn_profile_new.click)
        _pm.addAction("Profil laden", self.btn_profile_load.click)
        _pm.addAction("Profil speichern", self.btn_profile_save.click)
        _pm.addAction("Profil löschen", self.btn_profile_delete.click)
        self.btn_profile_menu.setMenu(_pm)
        for _b in (self.btn_profile_new, self.btn_profile_load, self.btn_profile_save, self.btn_profile_delete):
            _b.setVisible(False)

        self.tabs = QTabWidget()
        self.coach_tabs = QTabWidget()  # 0.5.0.0: Coach-Views gebuendelt
        layout.addWidget(self.tabs, stretch=6)

        dash_tab = QWidget(); dash_layout = QVBoxLayout(dash_tab)
        dash_layout.setContentsMargins(0, 8, 0, 0); dash_layout.setSpacing(12)
        sess = QGroupBox("SITZUNG"); sg = QGridLayout(sess); sg.setHorizontalSpacing(10)
        # 0.2.12: Setup-Auswahl aus der Sitzungsleiste entfernt (Widget bleibt intern aktiv)
        # 0.2.8: Fahrerprofil-Auswahl und "Fahrer & Hardware"-Button aus der Sitzungsleiste entfernt.
        sg.setColumnStretch(1, 1)
        dash_layout.addWidget(sess)
        self.dash_cards = {}
        card_grid = QGridLayout(); card_grid.setSpacing(10)
        for i, key in enumerate(["Verbindung", "Recording", "Runden", "Referenz", "Reifen", "Coach-Fokus"]):
            frame = QFrame(); frame.setObjectName("dashCard")
            frame.setMinimumHeight(84)
            fl = QVBoxLayout(frame); fl.setContentsMargins(16, 12, 16, 10); fl.setSpacing(3)
            lab = QLabel(key.upper()); lab.setObjectName("dashCardKey")
            val = QLabel("—"); val.setObjectName("dashCardVal"); val.setWordWrap(True)
            fl.addWidget(lab); fl.addWidget(val)
            self.dash_cards[key] = val
            card_grid.addWidget(frame, i // 3, i % 3)
        for c in range(3):
            card_grid.setColumnStretch(c, 1)
        card_grid.addWidget(LinkCard("WETTBEWERBE & RANGLISTEN", "RACEROOM COMPETITIONS IM BROWSER \u00d6FFNEN",
                                     RACEROOM_COMPETITIONS_URL), 2, 0, 1, 3)
        dash_layout.addLayout(card_grid)
        title_coach = QLabel("AKTUELLER COACH-FOKUS"); title_coach.setObjectName("sectionTitle")
        dash_layout.addWidget(title_coach)
        self.dash_coach = QTextEdit(); self.dash_coach.setReadOnly(True)
        self.dash_coach.setMinimumHeight(180)
        self.dash_coach.setStyleSheet("font-size:14px;")
        dash_layout.addWidget(self.dash_coach, 1)
        self.tabs.addTab(dash_tab, "Dashboard")

        live_tab = QWidget(); live_layout = QVBoxLayout(live_tab)
        # 0.2.11: Layout im Stil einer Results-Comparison (Vorbild-Screenshot):
        # Trackmap links, rechts Live-Zeile + Sektorzeiten + kompakte Rundenliste
        # mit farbcodierten Sektorzeiten (gruen = beste, rot = schwaecheste).
        self.trackmap = TrackMapWidget()
        self.trackmap.setMinimumWidth(320)
        self.live_summary = QTableWidget(0, 8)
        self.live_summary.setHorizontalHeaderLabels([
            "Aktuelle Runde", "Track m", "Speed", "Gang", "Fuel", "Letzte Runde", "Beste Runde", "Status"
        ])
        self.live_summary.horizontalHeader().setStretchLastSection(True)
        self.sector_label = QLabel("Sektorzeiten: warte auf erste vollst\u00e4ndige Runde \u2026")  # 0.4.9.0
        self.sector_label.setWordWrap(True)
        self.brake_status_label = QLabel("Bremsen: warte auf Telemetrie \u2026")  # 0.4.9.4
        self.brake_status_label.setWordWrap(True)
        self.live_lap_table = QTableWidget(0, 7)  # 0.2.11: Rundenliste im Results-Stil
        self.live_lap_table.setHorizontalHeaderLabels(["Lap", "Zeit", "S1", "S2", "S3", "Gap", "Fuel L"])
        self.live_lap_table.horizontalHeader().setStretchLastSection(True)
        self.live_lap_table.setAlternatingRowColors(True)
        self.live_lap_table.verticalHeader().setDefaultSectionSize(26)
        _live_right = QWidget(); _live_right.setProperty("plain", True)
        _live_right_layout = QVBoxLayout(_live_right); _live_right_layout.setContentsMargins(8, 0, 0, 0)
        _live_right_layout.addWidget(self.live_summary)
        _live_right_layout.addWidget(self.sector_label)
        _live_right_layout.addWidget(self.brake_status_label)
        _live_right_layout.addWidget(self.live_lap_table, 1)
        _live_split = QHBoxLayout()
        _live_split.addWidget(self.trackmap, 3)
        _live_split.addWidget(_live_right, 4)
        live_layout.addLayout(_live_split)
        live_layout.addWidget(self._hint("Live-Übersicht: Runden- und Statusdaten. Overlays über das Menü oben, " + self.hotkey_config.get("overlay", "F10") + " (Monitor) und " + self.hotkey_config.get("tire_overlay", "F6") + " (Reifen)."))
        self.live_tabs = QTabWidget()  # 0.2.12: Unterteiter unter Live (wie beim Coach)
        live_layout.addWidget(self.live_tabs, 2)  # 0.2.12: Reifen/Analyse/Runden/Vergleich/Heatmap
        self.tabs.addTab(live_tab, "Live")

        tires_tab = QWidget(); tires_layout = QVBoxLayout(tires_tab)
        tires_layout.addWidget(self._hint("Reifen live aus dem Shared Memory: Temperatur außen/mitte/innen, Druck, Verschleiß, Flat-/ABS-Warnung."))
        self.tire_table = QTableWidget(0, 10)
        self.tire_table.setHorizontalHeaderLabels(["Reifen", "Druck kPa", "Druck bar", "Temp außen", "Temp mitte", "Temp innen", "Carcass", "Wear/Rest %", "Flat/ABS", "Hinweis"])
        self.tire_table.horizontalHeader().setStretchLastSection(True)
        tires_layout.addWidget(self.tire_table)
        self.tire_note = QLabel("Noch keine Reifendaten.")
        self.tire_note.setWordWrap(True)
        tires_layout.addWidget(self.tire_note)
        self.live_tabs.addTab(tires_tab, "Reifen")

        setup_tab = QWidget(); setup_layout = QVBoxLayout(setup_tab)
        setup_layout.addWidget(self._hint("Empfehlungen aus Temperatur-Spread, Druck und Verschleiß. Keine automatische Setup-Änderung."))
        self.setup_coach_text = QTextEdit(); self.setup_coach_text.setReadOnly(True)
        self.setup_coach_text.setMinimumHeight(360)
        self.setup_coach_text.setStyleSheet("font-size:15px; line-height:1.35;")
        setup_layout.addWidget(self.setup_coach_text)
        self.coach_tabs.addTab(setup_tab, "Setup-Coach")

        analysis_tab = QWidget(); analysis_layout = QVBoxLayout(analysis_tab)
        self.zone_table = QTableWidget(0, 7)
        self.zone_table.setHorizontalHeaderLabels(["Zone", "Bereich", "Verlust", "Priorität", "Diagnose", "Handlung", "Speed Diff"])
        self.zone_table.horizontalHeader().setStretchLastSection(True)
        analysis_layout.addWidget(self._hint("Coach-Zonen statt 50-m-Sektorflut. Details stehen im Report."))
        analysis_layout.addWidget(self.zone_table)
        self.segment_table = QTableWidget(0, 9)
        self.segment_table.setHorizontalHeaderLabels(["Sektor", "Meter", "Samples", "Avg Speed", "Min Speed", "Max Brake", "Avg Thr", "Gear häufig", "Hinweis"])
        self.segment_table.setVisible(False)
        analysis_layout.addWidget(self.segment_table)
        self.live_tabs.addTab(analysis_tab, "Analyse")

        laps_tab = QWidget(); laps_layout = QVBoxLayout(laps_tab)
        laps_layout.addWidget(self._hint("S1/S2/S3 sind interne Streckendrittel. Grün = bester Wert, Rot = schwächster gültiger Wert."))
        self.lap_overview_table = QTableWidget(0, 8)
        self.lap_overview_table.setHorizontalHeaderLabels([
            "Lap", "S1", "S2", "S3", "Rundenzeit", "Min", "Max", "Durchschn."
        ])
        self.lap_overview_table.horizontalHeader().setStretchLastSection(True)
        self.lap_overview_table.setMinimumHeight(500)
        self.lap_overview_table.setAlternatingRowColors(True)
        self.lap_overview_table.verticalHeader().setDefaultSectionSize(30)
        laps_layout.addWidget(self.lap_overview_table, stretch=7)

        detail_label = QLabel("Detaildaten / Clean-Lap-Filter: Outlap/Pit/Standphase wird aussortiert. Beste gültige Runde wird als Referenz markiert.")
        detail_label.setMaximumHeight(22)
        laps_layout.addWidget(detail_label)
        self.laps_table = QTableWidget(0, 13)
        self.laps_table.setHorizontalHeaderLabels([
            "Lap", "Status", "Grund", "Samples", "Coverage m", "Dauer", "Max Speed",
            "Avg Speed", "Max Brake", "Fuel Used", "Start m", "End m", "Stand/Pit"
        ])
        self.laps_table.horizontalHeader().setStretchLastSection(True)
        self.laps_table.setMaximumHeight(170)
        self.laps_table.setMinimumHeight(90)
        self.laps_table.verticalHeader().setDefaultSectionSize(22)
        laps_layout.addWidget(self.laps_table, stretch=0)
        self.live_tabs.addTab(laps_tab, "Runden")

        compare_tab = QWidget(); compare_layout = QVBoxLayout(compare_tab)
        compare_layout.addWidget(self._hint("Positive Delta-Werte bedeuten Zeitverlust gegenüber der Referenzrunde."))
        compare_controls = QHBoxLayout()
        compare_controls.addWidget(QLabel("Referenz:"))
        self.ref_lap_combo = QComboBox(); self.ref_lap_combo.addItem("Auto", None)
        compare_controls.addWidget(self.ref_lap_combo)
        compare_controls.addWidget(QLabel("Vergleich:"))
        self.cmp_lap_combo = QComboBox(); self.cmp_lap_combo.addItem("Auto", None)
        compare_controls.addWidget(self.cmp_lap_combo)
        self.btn_apply_laps = QPushButton("Auswahl anwenden")
        compare_controls.addWidget(self.btn_apply_laps)
        self.btn_compare_import_ref = QPushButton("Referenz importieren")
        compare_controls.addWidget(self.btn_compare_import_ref)
        compare_controls.addStretch(1)
        compare_layout.addLayout(compare_controls)
        self.compare_table = QTableWidget(0, 13)
        self.compare_table.setHorizontalHeaderLabels([
            "Sektor", "Meter", "Vergleich", "Referenz", "Delta s", "Vgl Zeit", "Ref Zeit",
            "Vgl Avg", "Ref Avg", "Speed Diff", "Brake Diff", "Throttle Diff", "Hinweis"
        ])
        self.compare_table.horizontalHeader().setStretchLastSection(True)
        compare_layout.addWidget(self.compare_table)
        self.live_tabs.addTab(compare_tab, "Vergleich")

        heatmap_tab = QWidget(); heatmap_layout = QVBoxLayout(heatmap_tab)
        heatmap_layout.addWidget(self._hint("Vergleichsrunde gegen Referenz. Rot/Orange = Verlust, Grün = besser, Kreise = Coach-Zonen."))
        self.heatmap_metric_combo = QComboBox()
        self.heatmap_metric_combo.addItems(["Färbung: Delta (Zeitverlust)", "Färbung: Pedal-Input (Gas/Bremse)",
                                           "Färbung: Linienabweichung (Meter)", "Färbung: Gang & Drehzahl"])
        self.heatmap_metric_combo.currentIndexChanged.connect(
            lambda i: self.heatmap.set_heat_metric({1: "pedal", 2: "line", 3: "gear"}.get(i, "delta")))
        heatmap_layout.addWidget(self.heatmap_metric_combo)
        self.heatmap = TrackMapWidget()
        self.heatmap.setMinimumHeight(420)
        heatmap_layout.addWidget(self.heatmap, stretch=1)
        self.heatmap_note = QLabel("Nach Recording-Stopp oder Rundenauswahl wird die Heatmap automatisch aktualisiert.")
        self.heatmap_note.setWordWrap(True)
        heatmap_layout.addWidget(self.heatmap_note)
        self.live_tabs.addTab(heatmap_tab, "Heatmap")

        # 0.2.13: Sitzungs-Browser - gespeicherte Reports mit Datum/Name/Strecke/Fahrzeug/Runden/Bestzeit
        sessions_tab = QWidget(); sessions_layout = QVBoxLayout(sessions_tab)
        sessions_layout.addWidget(self._hint("Gespeicherte Aufzeichnungen. Doppelklick oder Button = Report anzeigen, Umbenennen vergibt einen eigenen Namen. Neue Sitzungen erscheinen automatisch nach dem Speichern."))
        self.sessions_table = QTableWidget(0, 6)
        self.sessions_table.setHorizontalHeaderLabels(["Datum", "Name", "Strecke", "Fahrzeug", "Runden", "Bestzeit"])
        self.sessions_table.horizontalHeader().setStretchLastSection(True)
        self.sessions_table.setAlternatingRowColors(True)
        self.sessions_table.verticalHeader().setDefaultSectionSize(26)
        self.sessions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # 0.2.14: Enum statt 0 - PySide6 meldet sonst TypeError beim Start
        self.sessions_table.doubleClicked.connect(lambda _i: self.open_session_report())
        sessions_layout.addWidget(self.sessions_table, 1)
        _sess_btns = QHBoxLayout()
        _b_sess_show = QPushButton("Report anzeigen"); _b_sess_show.clicked.connect(self.open_session_report)
        _b_sess_ren = QPushButton("Umbenennen"); _b_sess_ren.clicked.connect(self.rename_session)
        _b_sess_del = QPushButton("Löschen"); _b_sess_del.clicked.connect(self.delete_session)
        _b_sess_load = QPushButton("In Ansicht laden"); _b_sess_load.clicked.connect(self.load_session_into_views)
        _b_sess_ref = QPushButton("Aktualisieren"); _b_sess_ref.clicked.connect(self.refresh_sessions_table)
        _sess_btns.addWidget(_b_sess_show); _sess_btns.addWidget(_b_sess_ren); _sess_btns.addWidget(_b_sess_del); _sess_btns.addWidget(_b_sess_load); _sess_btns.addStretch(1); _sess_btns.addWidget(_b_sess_ref)
        sessions_layout.addLayout(_sess_btns)
        self.live_tabs.addTab(sessions_tab, "Sitzungen")

        # 0.2.21: Telemetrie-Reiter - G-G-Diagramm + Spuren (G-Kraefte, Lenkung, Pedale)
        telemetry_tab = QWidget(); telemetry_layout = QVBoxLayout(telemetry_tab)
        telemetry_layout.addWidget(self._hint("MoTeC-Stil: Gas (grün) und Bremse (rot) von 0 bis 100%, darunter die Lenkung zentriert, jeweils über die Rundenmeter. Rechts oben wird die Runde gewählt, die Input-Karte zeigt, wo auf der Strecke gas gegeben bzw. gebremst wird."))
        _tele_btns = QHBoxLayout()
        _tele_btns.addStretch(1)
        _tele_btns.addWidget(QLabel("Runde:"))
        self.telemetry_lap_combo = QComboBox()  # 0.2.25: einzelne Runden auswaehlbar
        self.telemetry_lap_combo.currentIndexChanged.connect(lambda _i: self.update_telemetry_view())
        _tele_btns.addWidget(self.telemetry_lap_combo)
        _b_tele_ref = QPushButton("Aktualisieren"); _b_tele_ref.clicked.connect(self.update_telemetry_view)
        _tele_btns.addWidget(_b_tele_ref)
        _b_tele_follow = QPushButton("Live folgen"); _b_tele_follow.clicked.connect(lambda: self._set_telemetry_cursor(None))  # 0.2.27
        _tele_btns.addWidget(_b_tele_follow)
        telemetry_layout.addLayout(_tele_btns)
        self.telemetry_trace = TelemetryTraceWidget()
        self.telemetry_trace.on_cursor = self._set_telemetry_cursor  # 0.2.27: Cursor ziehen
        telemetry_layout.addWidget(self.telemetry_trace, 3)
        self.telemetry_map = TelemetryMapWidget()  # 0.2.25: Input-Karte
        telemetry_layout.addWidget(self.telemetry_map, 2)
        self.telemetry_note = QLabel("")
        self.telemetry_note.setStyleSheet("color: #8f8f99; font-size: 12px;")
        telemetry_layout.addWidget(self.telemetry_note)
        self.live_tabs.addTab(telemetry_tab, "Telemetrie")

        coach_tab = QWidget(); coach_layout = QVBoxLayout(coach_tab)
        coach_layout.addWidget(self._hint("Zusammenhängende Kurven-/Bremszonen mit Verlust, Priorität und Fahranweisung."))
        self.coach_text = QTextEdit(); self.coach_text.setReadOnly(True); self.coach_text.setStyleSheet("font-size:15px; line-height:1.35;")
        coach_layout.addWidget(self.coach_text)
        self.coach_tabs.addTab(coach_tab, "Coach")

        limit_tab = QWidget(); limit_layout = QVBoxLayout(limit_tab)
        limit_layout.addWidget(self._hint("Kombiniert Vergleichszonen, Gas/Bremse, Rollenphase und Reifen-/Lockup-Status zu einem Limit-Level."))
        self.limit_coach_text = QTextEdit(); self.limit_coach_text.setReadOnly(True); self.limit_coach_text.setStyleSheet("font-size:15px; line-height:1.35;")
        limit_layout.addWidget(self.limit_coach_text, stretch=1)
        self.coach_tabs.addTab(limit_tab, "Limit-Coach")

        input_tab = QWidget(); input_layout = QVBoxLayout(input_tab)
        input_layout.addWidget(self._hint("Gas- und Bremsverhalten pro Runde: Bremspunkt, Bremslösung, Rollenphase, Gasannahme."))
        self.input_table = QTableWidget(0, 9)
        self.input_table.setHorizontalHeaderLabels(["Lap", "Max Bremse", "Ø Bremse", "Hartbrems.", "Löse-Sprünge", "Gas-Sprünge", "Rollen %", "Überlapp %", "Hinweis"])
        self.input_table.horizontalHeader().setStretchLastSection(True)
        self.input_table.setMinimumHeight(280)
        input_layout.addWidget(self.input_table, stretch=2)
        self.input_coach_text = QTextEdit(); self.input_coach_text.setReadOnly(True); self.input_coach_text.setStyleSheet("font-size:15px; line-height:1.35;")
        input_layout.addWidget(self.input_coach_text, stretch=1)
        self.coach_tabs.addTab(input_tab, "Input-Coach")
        self.tabs.addTab(self.coach_tabs, "Coach")  # 0.5.0.0: gebuendelte Coach-Ansicht
        self.coach_tabs.setCurrentWidget(coach_tab)  # Standard: Haupt-Coach

        hw_tab = QWidget(); hw_layout = QVBoxLayout(hw_tab)
        hw_layout.addWidget(self._hint("Fahrer-/Hardware-Profil. Settings-Screenshots werden ins Profil kopiert."))
        self.hw_edits = {}
        hw_grid = QGridLayout()
        hw_specs = [
            ("driver_name", "Fahrername", "z. B. Max Mustermann"),
            ("team", "Team/Handle", "z. B. JCM / PM_76"),
            ("wheelbase", "Lenkradbasis", "Simucube, Fanatec, Moza, Asetek, Logitech …"),
            ("wheel_settings", "FFB/Lenkung Settings", "Stärke, Damping, Friction, Slew Rate, Rotation …"),
            ("wheel_settings_screenshot", "Screenshot Lenkrad/FFB", "Bilddatei mit TrueDrive/Fanatec/Moza/FFB-Settings …"),
            ("pedals", "Pedale", "Simsonn, Heusinkveld, Fanatec, Asetek …"),
            ("brake_setup", "Brems-Setup", "Elastomere/Federn, Max-Kraft, Weg, Kalibrierung …"),
            ("pedal_settings_screenshot", "Screenshot Pedale", "Bilddatei mit Pedal-Kalibrierung/Bremskurve …"),
            ("brake_curve", "Bremskurve", "linear/progressiv, Deadzone, Gamma …"),
            ("throttle_setup", "Gas-Setup", "linear/progressiv, Deadzone, Feder, Weg …"),
            ("haptics", "Haptik", "HF8, Buttkicker, SimHub, keine …"),
            ("buttonbox", "Buttonbox 1 / Stream Deck", "Stream Deck, Buttonbox, Arduino, keine …"),
            ("buttonbox_2", "Buttonbox 2", "zweite Buttonbox, DDU, Zusatzpanel …"),
            ("buttonbox_3", "Buttonbox 3", "dritte Buttonbox / weiteres Eingabegerät …"),
            ("shifter", "Shifter/Handbremse", "sequentiell, H-Pattern, Handbremse, keine …"),
            ("display", "Anzeige", "VR, Triple, Ultrawide, Monitor …"),
            ("notes", "Notizen", "Besonderheiten, Verletzungen, Vorlieben …"),
        ]
        hw_dropdowns = {
            "wheelbase": ["", "Simucube 2 Sport", "Simucube 2 Pro", "Simucube 2 Ultimate", "Fanatec CSL DD", "Fanatec GT DD Pro", "Fanatec ClubSport DD", "Fanatec Podium DD1", "Fanatec Podium DD2", "Moza R5", "Moza R9", "Moza R12", "Moza R16", "Moza R21", "Asetek La Prima", "Asetek Forte", "Asetek Invicta", "SIMAGIC Alpha Mini", "SIMAGIC Alpha", "SIMAGIC Alpha Ultimate", "Logitech G Pro Wheel", "Thrustmaster T300", "Thrustmaster T818", "VRS DirectForce Pro", "Cammus", "Sonstige"],
            "pedals": ["", "Simsonn Plus", "Simsonn Plus X", "Simjack Pro", "Heusinkveld Sprint", "Heusinkveld Ultimate+", "Fanatec CSL Pedals LC", "Fanatec ClubSport V3", "Moza SR-P", "Moza CRP", "Asetek La Prima", "Asetek Forte", "Asetek Invicta", "SIMAGIC P1000", "SIMAGIC P2000", "VRS Pedals", "Venym Atrax", "Logitech G Pro Pedals", "Thrustmaster T-LCM", "Sonstige"],
            "brake_curve": ["", "linear", "leicht progressiv", "progressiv", "stark progressiv", "custom", "unbekannt"],
            "throttle_setup": ["", "linear", "leicht progressiv", "progressiv", "weicher Anfang", "Deadzone klein", "custom", "unbekannt"],
            "haptics": ["", "keine", "HF8", "Buttkicker", "Dayton/Nobsound", "SimHub Haptics", "Sonstige"],
            "buttonbox": ["", "keine", "Stream Deck Mini", "Stream Deck MK.2", "Stream Deck XL", "Buttonbox USB", "Arduino/DIY", "Leo Bodnar", "DDU", "Sonstige"],
            "buttonbox_2": ["", "keine", "Stream Deck Mini", "Stream Deck MK.2", "Stream Deck XL", "Buttonbox USB", "Arduino/DIY", "Leo Bodnar", "DDU", "Sonstige"],
            "buttonbox_3": ["", "keine", "Stream Deck Mini", "Stream Deck MK.2", "Stream Deck XL", "Buttonbox USB", "Arduino/DIY", "Leo Bodnar", "DDU", "Sonstige"],
            "shifter": ["", "keine", "Fanatec SQ", "SHH Shifter", "Thrustmaster TH8A", "Moza HGP", "Simagic DS-8X", "sequentiell", "H-Pattern", "Handbremse", "Sonstige"],
            "display": ["", "VR - Meta Quest 3", "VR - Meta Quest 2", "VR - Pimax", "VR - HP Reverb G2", "VR - Valve Index", "Single Monitor", "Ultrawide", "Triple Screen", "Sonstige"],
        }
        for i, (key, label, ph) in enumerate(hw_specs):
            hw_grid.addWidget(QLabel(label + ":"), i, 0)
            if key in hw_dropdowns:
                edit = QComboBox(); edit.setEditable(True); edit.addItems(hw_dropdowns[key]); edit.setToolTip("Links auf das Pfeilsymbol klicken oder eigenen Text eintippen.")
                if edit.lineEdit(): edit.lineEdit().setAlignment(Qt.AlignLeft)
                edit.setPlaceholderText(ph)
                self.hw_edits[key] = edit
                hw_grid.addWidget(edit, i, 1)
            elif key in ("wheel_settings_screenshot", "pedal_settings_screenshot"):
                edit = QLineEdit(); edit.setPlaceholderText(ph); edit.setReadOnly(False); edit.setToolTip("Pfad zum gespeicherten Profil-Screenshot. Bild wählen kopiert die Datei ins Profilverzeichnis.")
                btn = QPushButton("Bild wählen")
                btn.setToolTip("Screenshot/Bilddatei auswählen. Die Datei wird in den Profil-Assets-Ordner kopiert.")
                btn.clicked.connect(lambda _checked=False, k=key: self.select_settings_screenshot(k))
                row = QHBoxLayout(); row.setContentsMargins(0,0,0,0)
                row.addWidget(edit, stretch=1); row.addWidget(btn)
                cell = QWidget(); cell.setLayout(row)
                self.hw_edits[key] = edit
                hw_grid.addWidget(cell, i, 1)
            else:
                edit = QLineEdit(); edit.setPlaceholderText(ph)
                self.hw_edits[key] = edit
                hw_grid.addWidget(edit, i, 1)
        hw_grid.addWidget(QLabel("Pedal-Typ:"), len(hw_specs), 0)
        self.hw_pedal_type = QComboBox(); self.hw_pedal_type.addItems(["Loadcell", "Hydraulisch", "Potentiometer", "Sonstige/Unbekannt"]); self.hw_pedal_type.setToolTip("Links auf das Pfeilsymbol klicken.")
        self.hw_edits["pedal_type"] = self.hw_pedal_type
        hw_grid.addWidget(self.hw_pedal_type, len(hw_specs), 1)
        hw_layout.addLayout(hw_grid)
        # 0.4.8.1: Hilfetext entfernt
        self.hardware_coach_text = QTextEdit(); self.hardware_coach_text.setReadOnly(True); self.hardware_coach_text.setMaximumHeight(150)
        self.hardware_coach_text.setVisible(False)  # 0.4.8.1: aus der Ansicht genommen

        # 0.2.8: Ansicht "Fahrer & Hardware" entfernt - hw_tab wird nicht mehr als Reiter
        # angehaengt (auch kein Navi-Button mehr). Die Widgets bleiben erzeugt, damit die
        # Profil-Logik und alle Signal-Verbindungen stabil laufen.

        # 0.2.0: Navigation ueber die Seitenleiste; die Tab-Leiste des Hauptbereichs bleibt versteckt.
        self.tabs.tabBar().hide()
        from PySide6.QtWidgets import QButtonGroup
        self.nav_group = QButtonGroup(self); self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        _tab_index = {self.tabs.tabText(i): i for i in range(self.tabs.count())}
        for _label, _key in (("DASHBOARD", "Dashboard"), ("LIVE", "Live"), ("REIFEN", "Reifen"),
                             ("ANALYSE", "Analyse"), ("RUNDEN", "Runden"), ("VERGLEICH", "Vergleich"),
                             ("HEATMAP", "Heatmap"), ("COACH", "Coach")):
            if _key not in _tab_index:
                continue
            _b = QPushButton(_label); _b.setObjectName("navBtn"); _b.setCheckable(True)
            _b.setCursor(Qt.PointingHandCursor)
            _f = _b.font(); _f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3); _b.setFont(_f)
            _b.clicked.connect(lambda _c=False, k=_key: self.show_view(k))
            self.nav_group.addButton(_b); self.nav_box.addWidget(_b); self.nav_buttons[_key] = _b
        self.nav_box.addStretch(1)
        _ver = QLabel(f"PitBoss R3E  v{APP_VERSION}"); _ver.setObjectName("verLabel")
        self.nav_box.addWidget(_ver)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        # 0.2.10: Einfache Ansicht (Standard): nur Dashboard/Live/Coach sichtbar
        self.ui_simple = load_ui_layout()
        self.apply_ui_mode()
        self.show_view("Dashboard")
        self.refresh_sessions_table()  # 0.2.13
        self.view_timer = QTimer(self)  # 0.2.0: 2 Hz, nur sichtbare Ansicht
        self.view_timer.setInterval(500)
        self.view_timer.timeout.connect(self._view_tick)
        self.view_timer.start()

        self.log = QTextEdit(); self.log.setReadOnly(True)
        self._setup_file_logging()  # 0.4.8.8
        self.log.setMaximumHeight(115)
        self.log.setStyleSheet("font-size:11px;color:#c9d3e2;")
        self.log_label = QLabel("System-Log / Debug")
        layout.addWidget(self.log_label)
        layout.addWidget(self.log, stretch=1)
        self.log_label.setVisible(False); self.log.setVisible(False)  # 0.4.8.1: standardmaessig aus
        self.apply_profile_to_fields(self.current_profile_name)

        self.set_auto_bestlap_ui()
        self.set_auto_switch_ui()
        self.status.setText("Bereit. RaceRoom starten, ins Auto gehen, Aufnahme starten.")
        self.btn_snapshot.clicked.connect(self.snapshot)
        self.btn_record.clicked.connect(self.toggle_recording)
        self.btn_stop.clicked.connect(self.stop_recording)
        self.btn_report.clicked.connect(self.save_report)
        self.btn_csv.clicked.connect(self.save_csv)
        self.btn_clear.clicked.connect(self.clear)
        self.btn_export.clicked.connect(self.open_export_folder)
        self.btn_ref_export.clicked.connect(self.export_reference_lap)
        self.btn_ref_import.clicked.connect(self.import_reference_lap)
        self.btn_auto_bestlap.clicked.connect(self.toggle_auto_bestlap_export)
        self.btn_auto_switch.clicked.connect(self.toggle_auto_switch_recording)
        self.btn_live_log.clicked.connect(self.toggle_live_log)
        self.btn_overlay.clicked.connect(self.toggle_overlay)
        self.btn_tire_overlay.clicked.connect(self.toggle_tire_overlay)
        self.btn_pedal_overlay.clicked.connect(self.toggle_pedal_overlay)
        self.btn_apply_laps.clicked.connect(self.apply_lap_selection)
        self.btn_compare_import_ref.clicked.connect(self.import_reference_lap)
        self.setup_selector.currentTextChanged.connect(lambda _txt: self.refresh_dashboard())
        self.driver_profile_selector.currentTextChanged.connect(self.on_profile_changed)
        self.btn_profile_save.clicked.connect(self.save_current_hardware_profile)
        self.btn_profile_load.clicked.connect(self.import_hardware_profile_file)
        self.btn_profile_new.clicked.connect(self.new_hardware_profile)
        self.btn_profile_delete.clicked.connect(self.delete_current_hardware_profile)
        self.btn_fahrer_hardware.clicked.connect(self.select_fahrer_hardware_view)
        self.setup_hotkeys()
        self.setup_windows_global_hotkeys()
        self.refresh_dashboard()
        self._tag_plain_containers()  # 0.2.2



    def load_last_active_profile_name(self) -> str:
        """0.4.5.3: zuletzt aktives Fahrer-/Hardwareprofil merken."""
        try:
            if DRIVER_PROFILE_STATE_PATH.exists():
                data = json.loads(DRIVER_PROFILE_STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    name = str(data.get("last_active_profile", "")).strip()
                    if name and name in self.hardware_profiles:
                        return name
        except Exception:
            pass
        return next(iter(self.hardware_profiles.keys()), "Standard")

    def save_last_active_profile_name(self, name: str = None):
        try:
            n = (name or self.current_profile_name or self.selected_driver_profile_name() or "Standard").strip() or "Standard"
            DRIVER_PROFILE_STATE_PATH.write_text(json.dumps({"last_active_profile": n}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def default_hardware_profile(self, name: str = "Standard") -> dict:
        return {
            "driver_name": name,
            "team": "",
            "wheelbase": "",
            "wheel_settings": "",
            "wheel_settings_screenshot": "",
            "pedals": "",
            "pedal_type": "Loadcell",
            "brake_setup": "",
            "pedal_settings_screenshot": "",
            "brake_curve": "",
            "throttle_setup": "",
            "haptics": "",
            "buttonbox": "",
            "buttonbox_2": "",
            "buttonbox_3": "",
            "shifter": "",
            "display": "",
            "notes": "",
            "detected_devices": "",
            "detected_at": "",
        }

    def load_hardware_profiles(self) -> dict:
        try:
            if DRIVER_PROFILE_PATH.exists():
                data = json.loads(DRIVER_PROFILE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data:
                    return {str(k): (v if isinstance(v, dict) else self.default_hardware_profile(str(k))) for k, v in data.items()}
        except Exception:
            pass
        return {"Standard": self.default_hardware_profile("Standard")}

    def save_hardware_profiles(self):
        try:
            DRIVER_PROFILE_PATH.write_text(json.dumps(self.hardware_profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            try:
                self.log.append(f"Hardware-Profil konnte nicht gespeichert werden: {e}")
            except Exception:
                pass


    def normalize_imported_profile(self, name: str, value) -> dict:
        prof = self.default_hardware_profile(name)
        if isinstance(value, dict):
            prof.update(value)
        prof["profile_name"] = str(prof.get("profile_name") or name).strip() or name
        if not str(prof.get("driver_name") or "").strip():
            prof["driver_name"] = name
        return prof

    def unique_import_profile_name(self, base: str) -> str:
        base = (str(base or "Importiertes Profil").strip() or "Importiertes Profil")
        if base not in self.hardware_profiles:
            return base
        i = 2
        while True:
            candidate = f"{base} import {i}"
            if candidate not in self.hardware_profiles:
                return candidate
            i += 1

    def imported_profiles_from_json(self, data) -> dict:
        """Akzeptiert komplette driver_hardware_profiles.json oder ein einzelnes Profil-JSON."""
        if not isinstance(data, dict) or not data:
            return {}
        profile_keys = {"driver_name", "profile_name", "wheelbase", "pedals", "pedal_type", "brake_setup", "wheel_settings"}
        if any(k in data for k in profile_keys):
            base = str(data.get("profile_name") or data.get("driver_name") or "Importiertes Profil").strip() or "Importiertes Profil"
            return {base: self.normalize_imported_profile(base, data)}
        out = {}
        for key, value in data.items():
            if isinstance(value, dict):
                base = str(value.get("profile_name") or value.get("driver_name") or key).strip() or str(key)
                out[base] = self.normalize_imported_profile(base, value)
        return out

    def refresh_profile_selector_items(self):
        try:
            current = self.current_profile_name or self.selected_driver_profile_name()
            self.driver_profile_selector.blockSignals(True)
            self.driver_profile_selector.clear()
            self.driver_profile_selector.addItems(list(self.hardware_profiles.keys()))
            if current in self.hardware_profiles:
                self.driver_profile_selector.setCurrentText(current)
            self.driver_profile_selector.blockSignals(False)
        except Exception:
            try:
                self.driver_profile_selector.blockSignals(False)
            except Exception:
                pass

    def import_hardware_profile_file(self):
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Hardware-Profil laden",
                "",
                "JSON-Profile (*.json);;Alle Dateien (*.*)",
            )
            if not file_path:
                return
            src = Path(file_path)
            data = json.loads(src.read_text(encoding="utf-8"))
            imported = self.imported_profiles_from_json(data)
            if not imported:
                QMessageBox.warning(self, "Profil laden", "In dieser Datei wurde kein gültiges Hardwareprofil gefunden.")
                return
            added = []
            for base, prof in imported.items():
                name = self.unique_import_profile_name(base)
                prof["profile_name"] = name
                if not str(prof.get("driver_name") or "").strip():
                    prof["driver_name"] = name
                self.hardware_profiles[name] = prof
                added.append(name)
            self.current_profile_name = added[0]
            self.save_hardware_profiles()
            self.save_last_active_profile_name(self.current_profile_name)
            self.refresh_profile_selector_items()
            self.driver_profile_selector.setCurrentText(self.current_profile_name)
            self.apply_profile_to_fields(self.current_profile_name)
            msg = f"{len(added)} Profil(e) importiert: " + ", ".join(added[:4])
            if len(added) > 4:
                msg += f" … +{len(added)-4}"
            self.status.setText(msg)
            if hasattr(self, "log"):
                self.log.append(msg)
        except Exception as e:
            QMessageBox.warning(self, "Profil laden", f"Profil konnte nicht geladen werden:\n{e}")

    def select_settings_screenshot(self, key: str):
        """Select and copy a settings screenshot into the profile asset folder."""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Settings-Screenshot auswählen",
                "",
                "Bilder (*.png *.jpg *.jpeg *.webp *.bmp);;Alle Dateien (*.*)",
            )
            if not file_path:
                return
            src = Path(file_path)
            if not src.exists():
                QMessageBox.warning(self, "Screenshot", "Die ausgewählte Datei wurde nicht gefunden.")
                return
            profile = self.selected_driver_profile_name()
            safe_profile = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in profile)[:40] or "profile"
            target_dir = PROFILE_ASSET_DIR / safe_profile
            target_dir.mkdir(parents=True, exist_ok=True)
            prefix = "wheel" if "wheel" in key else "pedals"
            target = target_dir / f"{prefix}_settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}{src.suffix.lower()}"
            shutil.copy2(src, target)
            rel = str(target.relative_to(APP_DIR)) if target.is_relative_to(APP_DIR) else str(target)
            if key in getattr(self, "hw_edits", {}):
                self.set_widget_value(self.hw_edits[key], rel)
            # Direkt im aktuellen Profil sichern, damit der Bildpfad nicht verloren geht.
            try:
                prof = self.current_hardware_profile_from_fields()
                name = self.selected_driver_profile_name()
                self.hardware_profiles[name] = prof
                self.current_profile_name = name
                self.save_hardware_profiles()
            except Exception:
                pass
            if hasattr(self, "hardware_coach_text"):
                self.hardware_coach_text.setPlainText("\n".join(self.hardware_context_lines()))
            self.status.setText(f"Screenshot gespeichert: {rel}")
        except Exception as e:
            QMessageBox.warning(self, "Screenshot", f"Screenshot konnte nicht übernommen werden:\n{e}")

    def selected_driver_profile_name(self) -> str:
        try:
            txt = self.driver_profile_selector.currentText().strip()
        except Exception:
            txt = self.current_profile_name or "Standard"
        return txt or "Standard"

    def widget_value(self, w) -> str:
        try:
            if isinstance(w, QComboBox):
                return w.currentText().strip()
            return w.text().strip()
        except Exception:
            return ""

    def set_widget_value(self, w, val: str):
        val = str(val or "")
        try:
            if isinstance(w, QComboBox):
                idx = w.findText(val)
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    w.setCurrentText(val)
            else:
                w.setText(val)
        except Exception:
            pass

    def current_hardware_profile_from_fields(self) -> dict:
        prof = self.default_hardware_profile(self.selected_driver_profile_name())
        old_prof = self.hardware_profiles.get(self.selected_driver_profile_name(), {}) if hasattr(self, "hardware_profiles") else {}
        if isinstance(old_prof, dict):
            prof["detected_devices"] = old_prof.get("detected_devices", "")
            prof["detected_at"] = old_prof.get("detected_at", "")
        if hasattr(self, "hw_edits"):
            for key, w in self.hw_edits.items():
                prof[key] = self.widget_value(w)
        prof["profile_name"] = self.selected_driver_profile_name()
        if not prof.get("driver_name"):
            prof["driver_name"] = self.selected_driver_profile_name()
        return prof

    def apply_profile_to_fields(self, name: str):
        if not hasattr(self, "hw_edits"):
            return
        prof = self.hardware_profiles.get(name) or self.default_hardware_profile(name)
        self.current_profile_name = name
        self.save_last_active_profile_name(name)
        for key, w in self.hw_edits.items():
            self.set_widget_value(w, prof.get(key, ""))
        if hasattr(self, "hardware_coach_text"):
            self.hardware_coach_text.setPlainText("\n".join(self.hardware_context_lines()))
        self.refresh_dashboard()

    def on_profile_changed(self, name: str):
        name = (name or "Standard").strip() or "Standard"
        if name in self.hardware_profiles:
            self.apply_profile_to_fields(name)
        else:
            # Noch nicht speichern: erst Felder als neues Profil vorbereiten.
            self.current_profile_name = name
            if hasattr(self, "hw_edits"):
                prof = self.default_hardware_profile(name)
                for key, w in self.hw_edits.items():
                    self.set_widget_value(w, prof.get(key, ""))
            self.refresh_dashboard()

    def save_current_hardware_profile(self):
        name = self.selected_driver_profile_name()
        prof = self.current_hardware_profile_from_fields()
        self.hardware_profiles[name] = prof
        self.current_profile_name = name
        self.save_last_active_profile_name(name)
        # Combo aktualisieren ohne Duplikate
        if self.driver_profile_selector.findText(name) < 0:
            self.driver_profile_selector.addItem(name)
        self.save_hardware_profiles()
        if hasattr(self, "hardware_coach_text"):
            self.hardware_coach_text.setPlainText("\n".join(self.hardware_context_lines()))
        self.status.setText(f"Hardware-Profil gespeichert: {name}")
        self.refresh_dashboard()

    def new_hardware_profile(self):
        base = "Neuer Fahrer"
        name = base
        i = 2
        while name in self.hardware_profiles:
            name = f"{base} {i}"; i += 1
        self.hardware_profiles[name] = self.default_hardware_profile(name)
        self.driver_profile_selector.addItem(name)
        self.driver_profile_selector.setCurrentText(name)
        self.apply_profile_to_fields(name)
        self.save_hardware_profiles()
        self.status.setText(f"Neues Hardware-Profil angelegt: {name}")

    def delete_current_hardware_profile(self):
        name = self.selected_driver_profile_name()
        if name == "Standard" or len(self.hardware_profiles) <= 1:
            QMessageBox.information(self, "Profil löschen", "Das Standard-/letzte Profil kann nicht gelöscht werden.")
            return
        self.hardware_profiles.pop(name, None)
        idx = self.driver_profile_selector.findText(name)
        if idx >= 0:
            self.driver_profile_selector.removeItem(idx)
        self.save_hardware_profiles()
        next_name = next(iter(self.hardware_profiles.keys()), "Standard")
        self.driver_profile_selector.setCurrentText(next_name)
        self.apply_profile_to_fields(next_name)
        self.save_last_active_profile_name(next_name)
        self.status.setText(f"Hardware-Profil gelöscht: {name}")

    def selected_hardware_profile(self) -> dict:
        # Felder haben Vorrang, damit auch ungespeicherte Änderungen im Report landen.
        return self.current_hardware_profile_from_fields() if hasattr(self, "hw_edits") else self.hardware_profiles.get(self.current_profile_name, self.default_hardware_profile())

    def hardware_profile_summary(self, short: bool = False) -> str:
        p = self.selected_hardware_profile()
        name = p.get("driver_name") or p.get("profile_name") or self.selected_driver_profile_name()
        pedal = p.get("pedal_type") or "?"
        if short:
            return f"{name} | {pedal}"
        bits = [name]
        if p.get("wheelbase"):
            bits.append(p.get("wheelbase"))
        if p.get("pedals"):
            bits.append(p.get("pedals"))
        if pedal:
            bits.append(pedal)
        return " | ".join(bits)

    def resolve_profile_asset_path(self, value: str) -> Optional[Path]:
        value = str(value or "").strip()
        if not value:
            return None
        p = Path(value)
        if not p.is_absolute():
            p = APP_DIR / p
        return p

    def settings_screenshot_state(self, value: str) -> str:
        p = self.resolve_profile_asset_path(value)
        if not p:
            return "nicht gesetzt"
        return "vorhanden" if p.exists() else "Pfad gesetzt, Datei nicht gefunden"

    def settings_screenshot_status_text(self, profile: dict) -> str:
        wheel = self.settings_screenshot_state(profile.get("wheel_settings_screenshot"))
        pedals = self.settings_screenshot_state(profile.get("pedal_settings_screenshot"))
        return f"Lenkrad/FFB: {wheel} | Pedale: {pedals}"

    def hardware_context_lines(self) -> List[str]:
        p = self.selected_hardware_profile()
        lines = ["Hardware-/Settings-Kontext:"]
        lines.append(f"Fahrer: {p.get('driver_name') or self.selected_driver_profile_name()} | Team: {p.get('team') or '-'}")
        lines.append(f"Wheelbase: {p.get('wheelbase') or '-'} | Pedale: {p.get('pedals') or '-'} | Pedal-Typ: {p.get('pedal_type') or '-'}")
        lines.append(f"Bremse: {p.get('brake_setup') or '-'} | Kurve: {p.get('brake_curve') or '-'}")
        lines.append(f"Gas: {p.get('throttle_setup') or '-'} | Haptik: {p.get('haptics') or '-'} | Anzeige: {p.get('display') or '-'}")
        boxes = [p.get("buttonbox"), p.get("buttonbox_2"), p.get("buttonbox_3")]
        boxes_txt = " | ".join([b for b in boxes if b and b.lower() != "keine"]) or "-"
        lines.append(f"Buttonboxen: {boxes_txt} | Shifter/Handbremse: {p.get('shifter') or '-'}")
        shots = []
        if p.get("wheel_settings_screenshot"):
            shots.append("Lenkrad")
        if p.get("pedal_settings_screenshot"):
            shots.append("Pedale")
        if shots:
            lines.append("Settings-Screenshots: " + ", ".join(shots))
        lines.append("Settings-Bilder: " + self.settings_screenshot_status_text(p))
        lines.append("Coach-Regel: Erst Fahrtechnik prüfen, dann Hardware/Settings nur als mögliche Ursache vorschlagen.")
        return lines

    def hardware_report_lines(self) -> List[str]:
        p = self.selected_hardware_profile()
        lines = ["", "Fahrer-/Hardware-Profil 0.4.5.4:"]
        fields = [
            ("Profil", p.get("profile_name") or self.selected_driver_profile_name()),
            ("Fahrer", p.get("driver_name")),
            ("Team/Handle", p.get("team")),
            ("Lenkradbasis", p.get("wheelbase")),
            ("FFB/Lenkung Settings", p.get("wheel_settings")),
            ("Screenshot Lenkrad/FFB", p.get("wheel_settings_screenshot")),
            ("Pedale", p.get("pedals")),
            ("Pedal-Typ", p.get("pedal_type")),
            ("Brems-Setup", p.get("brake_setup")),
            ("Screenshot Pedale", p.get("pedal_settings_screenshot")),
            ("Bremskurve", p.get("brake_curve")),
            ("Gas-Setup", p.get("throttle_setup")),
            ("Haptik", p.get("haptics")),
            ("Buttonbox 1 / Stream Deck", p.get("buttonbox")),
            ("Buttonbox 2", p.get("buttonbox_2")),
            ("Buttonbox 3", p.get("buttonbox_3")),
            ("Shifter/Handbremse", p.get("shifter")),
            ("Anzeige", p.get("display")),
            ("Notizen", p.get("notes")),
            ("Settings-Screenshot Status", self.settings_screenshot_status_text(p)),
            ("KI-Auswertung vorbereitet", "ja" if (p.get("wheel_settings_screenshot") or p.get("pedal_settings_screenshot")) else "nein"),
        ]
        for label, val in fields:
            lines.append(f"{label}: {val or '-'}")
        lines.append("Hinweis: Dieses Profil wird manuell per Dropdown/freier Eingabe gepflegt. Screenshots werden als Profil-Assets gespeichert und bereiten die spätere KI-Auswertung der Lenkrad-/Pedalsettings vor.")
        return lines

    def hardware_input_hint(self, focus: str, rows: List[dict]) -> str:
        p = self.selected_hardware_profile()
        pedal_type = (p.get("pedal_type") or "").lower()
        if "Bremse ruhiger" in focus:
            if "load" in pedal_type:
                return "Hardware-Kontext: Bei Loadcell-Pedalen ggf. Max-Kraft/Kalibrierung oder eine leicht progressivere Bremskurve prüfen, falls das ruppige Lösen reproduzierbar bleibt."
            if "hyd" in pedal_type:
                return "Hardware-Kontext: Bei hydraulischen Pedalen Pedalweg, Endanschlag und Rückstellgefühl prüfen, falls das ruppige Lösen reproduzierbar bleibt."
            if "pot" in pedal_type:
                return "Hardware-Kontext: Bei Potentiometer-Pedalen Kalibrierung/Deadzone prüfen, falls die Bremse sprunghaft wirkt."
            return "Hardware-Kontext: Pedalkalibrierung, Pedalweg und Bremskurve prüfen, falls das ruppige Lösen reproduzierbar bleibt."
        if "Gas progressiver" in focus:
            return "Hardware-Kontext: Wenn die Gas-Sprünge trotz ruhigem Fuß bleiben, Gas-Pedalweg, Feder, Deadzone oder eine minimal weichere Gaskurve prüfen."
        if "Rollenphase" in focus:
            return "Hardware-Kontext: Wenn Rollen ungewollt entsteht, Brems-/Gas-Deadzone und Pedalruhe prüfen; zuerst aber Bremse/Gas fahrtechnisch klarer übergeben."
        return "Hardware-Kontext: Aktuell kein klarer Hardware-Eingriff nötig. Erst Fahrtechnik/Referenzzonen vergleichen."

    def _set_hw_if_empty(self, key: str, value: str):
        """Fill a hardware profile field only if it is still empty."""
        if not value or key not in getattr(self, "hw_edits", {}):
            return
        w = self.hw_edits[key]
        if not self.widget_value(w):
            self.set_widget_value(w, value)

    def scan_hardware_devices(self):
        """Best-effort Windows hardware scan for driver profiles.
        4.4.20 uses several Windows sources, but fills categories conservatively.
        Stale Joystick registry entries are kept as raw info only, not as trusted current hardware.
        """
        devices = []
        error = ""

        def add_device(name="", manufacturer="", cls="", device_id="", source=""):
            name = str(name or "").strip()
            manufacturer = str(manufacturer or "").strip()
            cls = str(cls or "").strip()
            device_id = str(device_id or "").strip()
            source = str(source or "").strip()
            if not name and not device_id:
                return
            devices.append({
                "name": name or device_id,
                "manufacturer": manufacturer,
                "class": cls,
                "device_id": device_id,
                "source": source,
            })

        if sys.platform.startswith("win"):
            ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
$all = @()
$all += Get-CimInstance Win32_PnPEntity | Select-Object @{n='Source';e={'PnPEntity'}},Name,Manufacturer,PNPClass,DeviceID
$all += Get-PnpDevice -PresentOnly | Select-Object @{n='Source';e={'PnpDevice'}},@{n='Name';e={$_.FriendlyName}},Manufacturer,@{n='PNPClass';e={$_.Class}},@{n='DeviceID';e={$_.InstanceId}}
$usb = Get-CimInstance Win32_USBControllerDevice
foreach ($u in $usb) {
    try {
        $dep = [WMI]$u.Dependent
        if ($dep) { $all += $dep | Select-Object @{n='Source';e={'USBController'}},Name,Manufacturer,PNPClass,DeviceID }
    } catch {}
}
$joyPaths = @(
 'HKCU:\System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\*',
 'HKLM:\SYSTEM\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\*'
)
foreach ($jp in $joyPaths) {
    Get-ItemProperty $jp | ForEach-Object {
        $n = $_.OEMName
        if ($n) {
            [PSCustomObject]@{Source='JoystickOEM';Name=$n;Manufacturer='';PNPClass='GameController';DeviceID=$_.PSChildName}
        }
    } | ForEach-Object { $all += $_ }
}
$all | Where-Object { $_.Name -or $_.DeviceID } | ConvertTo-Json -Depth 3
"""
            try:
                ps_cmd = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $OutputEncoding=[System.Text.Encoding]::UTF8; " + ps
                cp = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                                    capture_output=True, text=False, timeout=20)
                stdout = (cp.stdout or b"").decode("utf-8", errors="replace")
                stderr = (cp.stderr or b"").decode("utf-8", errors="replace")
                if cp.returncode == 0 and stdout.strip():
                    data = json.loads(stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data if isinstance(data, list) else []:
                        add_device(
                            item.get("Name"),
                            item.get("Manufacturer"),
                            item.get("PNPClass"),
                            item.get("DeviceID"),
                            item.get("Source"),
                        )
                else:
                    error = (stderr or stdout or "PowerShell lieferte keine Geräte.").strip()[:500]
            except Exception as e:
                error = str(e)
        else:
            error = "Hardware-Scan ist aktuell für Windows ausgelegt."

        names = []
        seen = set()
        for d in devices:
            did = d.get("device_id", "")
            line = " | ".join([x for x in [d.get("name"), d.get("manufacturer"), d.get("class"), did, d.get("source")] if x])
            key = line.lower()
            if line and key not in seen:
                seen.add(key)
                names.append(line)

        def low_line(line):
            return line.lower().replace("_", " ").replace("-", " ")

        def find_any(keywords, exclude=()):
            """Return a conservative category suggestion.
            Important: Windows keeps old joystick OEM registry entries. Those are useful
            as raw info, but must not automatically become the current wheelbase/pedal.
            """
            best = ""
            best_score = -999
            for line in names:
                low = low_line(line)
                if exclude and any(e in low for e in exclude):
                    continue
                if not any(k in low for k in keywords):
                    continue
                # JoystickOEM entries are often stale/old devices. Keep them in raw scan,
                # but do not use them to fill current hardware fields.
                if "joystickoem" in low:
                    continue
                score = 0
                known_brand = any(k in low for k in ["simucube", "fanatec", "moza", "asetek", "simagic", "heusinkveld", "simsonn", "simjack", "stream deck", "elgato", "quest", "pico", "vive", "pimax", "buttkicker", "hf8"])
                if known_brand:
                    score += 10
                if "pnpdevice" in low or "pnpentity" in low or "usbcontroller" in low:
                    score += 3
                if "gamecontroller" in low:
                    score += 1
                if "hidclass" in low or "usb input device" in low or "hid compliant" in low:
                    score -= 3
                if "keyboard" in low or "mouse" in low:
                    score -= 8
                # Need a reasonably specific hit before autofill.
                if score > best_score and score >= 6:
                    best_score = score
                    best = line.split(" | ")[0]
            return best

        wheel_keywords = [
            "simucube", "granite", "fanatec", "clubsport", "podium", "csl dd", "moza", "r5", "r9", "r12", "r16", "r21",
            "asetek", "la prima", "forte", "invicta", "simagic", "alpha", "logitech", "g pro", "thrustmaster", "t300", "t818",
            "cammus", "vrs directforce", "directforce", "wheel base", "wheelbase", "racing wheel"
        ]
        pedal_keywords = [
            "simsonn", "heusinkveld", "sprint", "ultimate", "fanatec pedals", "clubsport pedals", "csl pedals", "moza pedals",
            "crp", "sr p", "asetek pedals", "invicta pedals", "forte pedals", "simagic p", "p1000", "p2000", "simjack", "vrs pedals", "venym", "pedal", "load cell", "loadcell"
        ]
        haptic_keywords = ["hf8", "haptic", "buttkicker", "next level racing", "nobsound", "dayton audio", "simhub"]
        display_keywords = ["quest", "oculus", "meta", "pico", "vive", "valve index", "reverb", "pimax", "vr headset", "mixed reality"]
        button_keywords = ["stream deck", "elgato", "button box", "buttonbox", "arduino", "leo bodnar", "bbi", "joystick controller", "game controller"]
        shifter_keywords = ["shifter", "shift", "handbrake", "hand brake", "sequential", "h-pattern", "th8a", "shh", "sq v", "ds-8x", "hgp"]

        wheel = find_any(wheel_keywords, exclude=("pedal", "button", "stream deck"))
        pedals = find_any(pedal_keywords, exclude=("wheel base", "wheelbase", "stream deck"))
        haptics = find_any(haptic_keywords)
        display = find_any(display_keywords)
        buttonbox = find_any(button_keywords, exclude=("keyboard", "mouse"))
        shifter = find_any(shifter_keywords, exclude=("keyboard", "mouse"))

        generic_controllers = []
        for line in names:
            low = low_line(line)
            if any(k in low for k in ["hid compliant game controller", "usb input device", "gamecontroller", "joystick"]):
                if not any(bad in low for bad in ["keyboard", "mouse", "touchpad"]):
                    generic_controllers.append(line.split(" | ")[0])
        generic_controllers = list(dict.fromkeys(generic_controllers))[:8]

        # Nur eindeutige, aktuelle Treffer automatisch übernehmen.
        # Alte Registry-/Joystick-OEM-Einträge bleiben als Rohdaten sichtbar,
        # werden aber nicht mehr in Base/Pedale/Shifter geschrieben.
        self._set_hw_if_empty("wheelbase", wheel)
        self._set_hw_if_empty("pedals", pedals)
        self._set_hw_if_empty("haptics", haptics)
        self._set_hw_if_empty("buttonbox", buttonbox)
        self._set_hw_if_empty("shifter", shifter)
        self._set_hw_if_empty("display", display)

        notes_widget = self.hw_edits.get("notes")
        notes = self.widget_value(notes_widget)
        note_lines = []
        if buttonbox and buttonbox.lower() not in notes.lower():
            note_lines.append(f"Buttonbox/Controller-Vorschlag: {buttonbox}")
        if shifter and shifter.lower() not in notes.lower():
            note_lines.append(f"Shifter/Handbremse-Vorschlag: {shifter}")
        if generic_controllers:
            note_lines.append("Generische HID/Gamecontroller erkannt, bitte manuell zuordnen: " + ", ".join(generic_controllers))
        stale = [ln.split(" | ")[0] for ln in names if "joystickoem" in low_line(ln)]
        if stale:
            note_lines.append("Alte/Registry-Gamecontroller gefunden, nicht automatisch übernommen: " + ", ".join(list(dict.fromkeys(stale))[:8]))
        if note_lines and notes_widget is not None:
            add = "\n".join(note_lines)
            self.set_widget_value(notes_widget, (notes + "\n" + add).strip() if notes else add)

        prof = self.current_hardware_profile_from_fields()
        prof["detected_at"] = datetime.now().isoformat(timespec="seconds")
        prof["detected_devices"] = "; ".join(names[:120]) if names else ("Scan ohne Ergebnis" + (f": {error}" if error else ""))
        prof["detected_summary"] = " | ".join([x for x in [f"Wheelbase: {wheel}" if wheel else "", f"Pedale: {pedals}" if pedals else "", f"Haptik: {haptics}" if haptics else "", f"Anzeige/VR: {display}" if display else "", f"Buttonbox: {buttonbox}" if buttonbox else "", f"Shifter: {shifter}" if shifter else ""] if x]) or "Keine eindeutige Kategorie erkannt"
        name = self.selected_driver_profile_name()
        self.hardware_profiles[name] = prof
        self.current_profile_name = name
        self.save_hardware_profiles()
        if hasattr(self, "hardware_coach_text"):
            lines = self.hardware_context_lines()
            lines.append("")
            lines.append("Hardware-Scan 4.4.20:")
            lines.append(prof.get("detected_summary", ""))
            if generic_controllers:
                lines.append("Hinweis: Einige Geräte melden sich nur generisch. Diese stehen in den Notizen und können manuell zugeordnet werden.")
            lines.append("Hinweis: Alte Windows-Registry/Joystick-OEM-Geräte werden nicht mehr automatisch als aktuelle Hardware übernommen.")
            if names:
                lines.append("")
                lines.append(f"Erkannte Geräte/Rohdaten: {len(names)}")
                for line in names[:28]:
                    lines.append("- " + line)
                if len(names) > 28:
                    lines.append(f"... {len(names)-28} weitere im Profil gespeichert")
            else:
                lines.append("")
                lines.append("Keine Geräte erkannt. " + error)
            self.hardware_coach_text.setPlainText("\n".join(lines))
        self.status.setText(f"Hardware-Scan abgeschlossen: {len(names)} Einträge, Kategorie: {prof.get('detected_summary','')}")
        self.refresh_dashboard()

    def cleanup_duplicate_overlays(self):
        # Sicherheitsnetz: Es darf pro App nur ein Overlay-Fenster geben.
        # Falls durch ältere Builds/Hotkey-Doppelung mehrere Top-Level-Overlays existieren,
        # werden alle außer self.overlay_window geschlossen.
        try:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, OverlayWindow) and w is not self.overlay_window:
                    w.close()
                    w.deleteLater()
        except Exception as e:
            self.log.append(f"Overlay-Duplikat-Cleanup Hinweis: {e}")

    def cleanup_duplicate_tire_overlays(self):
        try:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, TireOverlayWindow) and w is not self.tire_overlay_window:
                    w.close()
                    w.deleteLater()
        except Exception as e:
            self.log.append(f"Reifen-Overlay-Duplikat-Cleanup Hinweis: {e}")

    def _hint(self, text):
        lab = QLabel(text); lab.setObjectName("hint"); lab.setWordWrap(True)
        return lab

    def show_view(self, key):
        """0.2.0: Ansicht ueber Namen waehlen; Seitenleiste und Tabs bleiben synchron."""
        idx = None
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == key:
                idx = i
                break
        if idx is None:
            return
        self.tabs.setCurrentIndex(idx)
        b = getattr(self, "nav_buttons", {}).get(key)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def maybe_autoshow_tire_overlay(self, s):
        # Overlay einmal pro Sitzung automatisch oeffnen, sobald der Fahrer auf der Strecke ist.
        # Danach bleibt es dem Nutzer ueberlassen (Button/F6). Kein erneutes Aufpoppen nach Schliessen.
        if not getattr(self, "tire_overlay_autostart", True):
            return
        if getattr(self, "_tire_overlay_autoshown", False):
            return
        try:
            on_track = (not self.is_non_driving_sample(s)) and s.speed_kmh > 3 and bool(getattr(s, "player_has_vehicle", True))
        except Exception:
            on_track = False
        if not on_track:
            return
        try:
            if self.tire_overlay_window is None:
                self.tire_overlay_window = TireOverlayWindow()
                try:
                    self.tire_overlay_window.apply_overlay_style(getattr(self, "overlay_style", "transparent"))  # 0.4.9.1
                except Exception:
                    pass
            self.cleanup_duplicate_tire_overlays()
            if not self.tire_overlay_window.isVisible():
                self.tire_overlay_window.update_from_main(self)
                self.tire_overlay_window.show()
                self.tire_overlay_window.raise_()
                self.log.append("Reifen-Overlay automatisch geoeffnet (Fahrt erkannt).")
            self._tire_overlay_autoshown = True
        except Exception as e:
            try:
                self.log.append(f"Auto-Overlay Hinweis: {e}")
            except Exception:
                pass

    def toggle_tire_overlay(self):
        if self.tire_overlay_window is None:
            self.tire_overlay_window = TireOverlayWindow()
            try:
                self.tire_overlay_window.apply_overlay_style(getattr(self, "overlay_style", "transparent"))  # 0.4.9.1
            except Exception:
                pass
        self.cleanup_duplicate_tire_overlays()
        if self.tire_overlay_window.isVisible():
            self.tire_overlay_window.hide()
            self.log.append("Reifen-Overlay ausgeblendet.")
        else:
            self.cleanup_duplicate_tire_overlays()
            self.tire_overlay_window.update_from_main(self)
            self.tire_overlay_window.show()
            self.tire_overlay_window.raise_()
            self.log.append("Reifen-Overlay geöffnet. Separates Fenster neben dem Coach-Overlay.")

    def toggle_corner_name_overlay(self):
        # 0.2.37: Kurvennamen-Overlay (Mehr-Menue oder Hotkey 'Kurven-Namen-Overlay').
        if self.corner_name_overlay_window is None:
            self.corner_name_overlay_window = CornerNameOverlayWindow()
            try:
                self.corner_name_overlay_window.apply_overlay_style(getattr(self, "overlay_style", "transparent"))
            except Exception:
                pass
        if self.corner_name_overlay_window.isVisible():
            self.corner_name_overlay_window.hide()
            self.log.append("Kurven-Namen-Overlay ausgeblendet.")
        else:
            self.update_corner_name_overlay(force=True)
            self.corner_name_overlay_window.show()
            self.corner_name_overlay_window.raise_()
            self.log.append("Kurven-Namen-Overlay geoeffnet. Naechste Kurve mit Name und Distanz.")

    def open_corner_name_dialog(self):
        # 0.2.37: erkannte Kurven benennen; Namen landen je Strecke in corner_names.json.
        corners = getattr(self, "corner_list", None) or []
        if not corners:
            QMessageBox.information(self, "Kurven benennen",
                "Es sind noch keine Kurven erkannt.\n\n"
                "Fahre erst eine vollstaendige Runde auf der Strecke - PitBoss erkennt "
                "die Kurven automatisch am Ende der Runde.")
            return
        track = getattr(self, "corner_track", "") or self._corner_track_key()
        data = load_corner_names()
        names = dict(data.get(track, {}))
        dlg = QDialog(self)
        dlg.setWindowTitle("Kurven benennen - " + (track or "Strecke"))
        dlg.setMinimumWidth(520)
        lay = QVBoxLayout(dlg)
        tip = QLabel("Eigene Namen fuer die erkannten Kurven (leer lassen = K1, K2, ...). Reihenfolge = Fahrtrichtung.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        table = QTableWidget(len(corners), 3)
        table.setHorizontalHeaderLabels(["Nr", "Richtung", "Name"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        for i, c in enumerate(corners):
            it0 = QTableWidgetItem("K" + str(c.get("idx", i + 1)))
            it0.setFlags(Qt.ItemIsEnabled)
            direction = "links" if c.get("dir") == "L" else "rechts"
            it1 = QTableWidgetItem(direction + " (" + str(int(round(float(c.get("turn_deg", 0.0))))) + " Grad)")
            it1.setFlags(Qt.ItemIsEnabled)
            table.setItem(i, 0, it0)
            table.setItem(i, 1, it1)
            table.setItem(i, 2, QTableWidgetItem(str(names.get(str(c.get("idx")), "") or "")))
        lay.addWidget(table)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.Accepted:
            for i, c in enumerate(corners):
                it = table.item(i, 2)
                v = (it.text().strip() if it else "")
                if v:
                    names[str(c.get("idx"))] = v
                else:
                    names.pop(str(c.get("idx")), None)
            data[track] = names
            if save_corner_names(data):
                self.log.append("Kurvennamen gespeichert (" + track + ") fuer " + str(len(names)) + " Kurve(n).")
                self.status.setText("Kurvennamen gespeichert.")
                self.update_corner_name_overlay(force=True)

    def _corner_track_key(self) -> str:
        s = self.last_live_sample or (self.samples[-1] if self.samples else None)
        return (getattr(s, "track", "") or "").strip()

    def _corner_display_name(self, corner) -> str:
        names = load_corner_names().get(getattr(self, "corner_track", ""), {})
        v = str(names.get(str(corner.get("idx")), "") or "").strip()
        return v if v else ("K" + str(corner.get("idx", "?")))

    def refresh_corner_list(self, rows):
        """0.2.37: nach einer abgeschlossenen Runde Kurven erkennen und pro Strecke cachen."""
        try:
            corners = detect_corners_from_rows(rows)
            if not corners:
                return
            key = self._corner_track_key()
            if not key:
                return
            self.corner_list = corners
            self.corner_track = key
            track_m = max([float(getattr(r, "lap_dist_m", 0.0) or 0.0) for r in rows] or [0.0])
            self.corner_track_len = track_m if track_m > 100.0 else 0.0
            self.log.append("Kurven erkannt (" + key + "): " + str(len(corners)) +
                            " - benennbar ueber Mehr > Kurven benennen ...")
            self.update_corner_name_overlay()
        except Exception as e:
            try:
                self.log.append("Kurven-Erkennung fehlgeschlagen: " + type(e).__name__ + ": " + str(e))
            except Exception:
                pass

    def update_corner_name_overlay(self, force=False):
        # 0.2.37: naechste Kurve (Name, Richtung, Distanz) ins Overlay schreiben.
        w = getattr(self, "corner_name_overlay_window", None)
        if w is None or not (w.isVisible() or force):
            return
        corners = getattr(self, "corner_list", None) or []
        track = self._corner_track_key()
        if not corners or track != getattr(self, "corner_track", ""):
            w.set_info(track, "-", "", None)
            return
        s = self.last_live_sample
        if s is None:
            w.set_info(track, "-", "", None)
            return
        cur = float(getattr(s, "lap_dist_m", -1.0) or 0.0)
        if cur < 0:
            w.set_info(track, "-", "", None)
            return
        tl = float(getattr(s, "track_length_m", 0.0) or 0.0)
        if tl <= 0:
            tl = float(getattr(self, "corner_track_len", 0.0) or 0.0)
        # 0.2.38: Layout in der eingebauten Kurvennamen-Datenbank? -> echte Namen
        layout_id = int(getattr(s, "layout_id", 0) or 0)
        sections = CORNER_SECTIONS.get(layout_id) if layout_id else None
        if sections:
            cur_sec = None
            for sec in sections:
                if sec[0] <= cur <= sec[1]:
                    cur_sec = sec
                    break
            nxt, nxt_d = None, None
            for sec in sections:
                d = float(sec[0]) - cur
                if d < 0 and tl > 100.0:
                    d += tl
                if d < 0:
                    continue
                if sec[2] == "Start-Finish":
                    continue
                if nxt is None or d < nxt_d:
                    nxt, nxt_d = sec[2], d
            if cur_sec is not None and cur_sec[2] != "Start-Finish":
                w.set_info(track, cur_sec[2], "", nxt_d)
            elif nxt is not None:
                w.set_info(track, nxt, "", nxt_d)
            else:
                w.set_info(track, "-", "", None)
            return
        best, best_d = None, None
        for c in corners:
            d = float(c.get("lap_dist_m", 0.0)) - cur
            if d < -30.0 and tl > 100.0:
                d += tl  # Kurve liegt hinter uns -> naechste Runde
            if d < 15.0:
                continue  # mitten in der Kurve -> die uebernaechste suchen
            if best is None or d < best_d:
                best, best_d = c, d
        if best is None:
            w.set_info(track, "-", "", None)
            return
        w.set_info(track, self._corner_display_name(best), best.get("dir", ""), best_d)

    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def _ai_config_path(self):
        return str(EXPORT_DIR / "ai_config.json")

    def set_ai_config(self, cfg):
        """Wird vom Einstellungsfenster gerufen: uebernehmen und speichern."""
        self.ai_cfg = cfg
        try:
            ai_providers.save_config(self._ai_config_path(), cfg)
        except Exception as e:
            self.log.append(f"KI-Einstellungen konnten nicht gespeichert werden: {e}")
        self.live_coach.ai_last_error = ""
        self.log.append("KI-Coach: " + (ai_providers.label(cfg) if ai_providers.is_active(cfg)
                                         else "lokal (ohne KI)"))
        self._refresh_live_coach_status()

    def _refresh_live_coach_status(self):
        if getattr(self, "live_coach_enabled", False):
            ki = (" \u2013 KI: " + ai_providers.label(self.ai_cfg)) if ai_providers.is_active(self.ai_cfg) else ""
            self.status.setText("Live-Coach AN" + ki + " \u2013 Sprachhinweise auf der Geraden (F11).")

    def open_settings_window(self):
        if getattr(self, "settings_window", None) is None:
            self.settings_window = SettingsWindow(self)
            self.settings_window.setStyleSheet(LIGHT_QSS if getattr(self, "_theme", "dark") == "light" else DARK_QSS)
        self.settings_window.show(); self.settings_window.raise_(); self.settings_window.activateWindow()

    def toggle_log(self):
        vis = not self.log.isVisible()
        self.log.setVisible(vis); self.log_label.setVisible(vis)

    def _theme_path(self):
        return str(EXPORT_DIR / "ui_theme.txt")

    def _load_theme(self):
        try:
            with open(self._theme_path(), encoding="utf-8") as fh:
                m = fh.read().strip()
                return m if m in ("dark", "light") else "dark"
        except Exception:
            return "dark"

    def _save_theme(self, mode):
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(self._theme_path(), "w", encoding="utf-8") as fh:
                fh.write(mode)
        except Exception:
            pass

    def _style_rr_logo(self):
        """Das Logo hat weisse Schrift: im hellen Design bekommt es einen dunklen Chip."""
        lab = getattr(self, "brand_logo", None)
        if lab is None:
            return
        if getattr(self, "_theme", "dark") == "light":
            lab.setStyleSheet("background:#101013; border-radius:2px; padding:4px 10px;")
        else:
            lab.setStyleSheet("background:transparent;")

    def nav_step(self, delta):
        """0.2.2: Pfeile der Navigation: eine Ansicht vor/zurueck (in Reihenfolge der Reiter)."""
        keys = [k for k, b in self.nav_buttons.items() if not b.isHidden()]  # 0.2.10: versteckte (Einfache Ansicht) ueberspringen
        cur = next((k for k, b in self.nav_buttons.items() if b.isChecked()), keys[0] if keys else None)
        if cur is None:
            return
        i = max(0, min(len(keys) - 1, keys.index(cur) + delta))
        self.show_view(keys[i])

    def apply_ui_mode(self):
        """0.2.10: Einfache Ansicht - Navi-Buttons der Nebenansichten verstecken/zeigen."""
        simple = getattr(self, "ui_simple", True)
        for key, b in getattr(self, "nav_buttons", {}).items():
            b.setHidden(simple and key not in SIMPLE_VIEWS)
        if simple:
            cur = next((k for k, b in self.nav_buttons.items() if b.isChecked()), None)
            if cur is not None and cur not in SIMPLE_VIEWS:
                self.show_view("Dashboard")
        act = getattr(self, "act_ui_simple", None)
        if act is not None:
            act.setChecked(simple)

    def toggle_ui_mode(self, simple=None):
        """0.2.10: Einfache <-> Experte-Ansicht umschalten und merken."""
        if simple is None:
            simple = not getattr(self, "ui_simple", True)
        self.ui_simple = bool(simple)
        save_ui_layout(self.ui_simple)
        self.apply_ui_mode()
        label = "Einfache Ansicht (Dashboard/Live/Coach)" if self.ui_simple else "Experte-Ansicht (alle Ansichten)"
        if hasattr(self, "status"):
            self.status.setText("Ansicht: " + label + " | umschalten: Mehr \u25be \u2192 Einfache Ansicht")
        if hasattr(self, "log"):
            self.log.append("Ansicht umgeschaltet: " + label)

    def _tag_plain_containers(self):
        """0.2.2: Reine Layout-Container werden transparent, damit der Verlaufshintergrund
        durchscheint (QSS 'QWidget { background }' wuerde sie sonst einfarbig fuellen)."""
        root = getattr(self, "_root", None)
        if root is None:
            return
        for w in root.findChildren(QWidget):
            if type(w) is QWidget and not w.objectName().startswith("qt_") and not w.property("plain"):
                w.setProperty("plain", True)
        self._root.setStyleSheet(self._root.styleSheet())  # Stil neu aufloesen

    def apply_theme(self, mode):
        self._theme = mode if mode in ("dark", "light") else "dark"
        qss = LIGHT_QSS if self._theme == "light" else DARK_QSS
        self._root.setStyleSheet(qss)
        sw = getattr(self, "settings_window", None)
        if sw is not None:
            sw.setStyleSheet(qss)
        self._style_rr_logo()  # 0.4.9.3

    def toggle_theme(self):
        self.apply_theme("light" if self._theme == "dark" else "dark")
        self._save_theme(self._theme)

    def _check_updates(self):
        self.log.append("Pruefe auf Updates \u2026")
        QApplication.processEvents()
        try:
            info = updater.check_for_update(APP_VERSION)
        except Exception as e:
            QMessageBox.warning(self, "Update", f"Update-Pruefung fehlgeschlagen: {e}")
            return
        if info is None:
            QMessageBox.information(self, "Update", f"Du bist aktuell (v{APP_VERSION}).")
            return
        self._show_update_dialog(info)

    def _auto_check_updates(self):
        """Beim Start: im Hintergrund pruefen; nur melden, wenn ein neueres Release existiert."""
        self._upd_check = UpdateCheckWorker()

        def on_result(info, err):
            if err:
                self.log.append(f"Auto-Update-Pruefung: {err}")
            elif info is not None:
                self.log.append(f"Update verfuegbar: {info.get('version')}")
                self._show_update_dialog(info)

        self._upd_check.result.connect(on_result)
        self._upd_check.start()

    def _show_update_dialog(self, info):
        box = QMessageBox(self)
        box.setWindowTitle("Update verf\u00fcgbar")
        box.setText(f"Neue Version {info['version']} verf\u00fcgbar.\nInstalliert: {APP_VERSION}.")
        if info.get("notes"):
            box.setInformativeText(info["notes"][:600])
        dl_btn = None
        if info.get("asset_url"):
            dl_btn = box.addButton("Herunterladen & installieren", QMessageBox.AcceptRole)
        open_btn = box.addButton("Download-Seite \u00f6ffnen", QMessageBox.AcceptRole)
        box.addButton("Sp\u00e4ter", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if dl_btn is not None and clicked is dl_btn:
            self._download_and_launch(info)
        elif clicked is open_btn:
            QDesktopServices.openUrl(QUrl(info["url"]))

    def _download_and_launch(self, info):
        import os
        url = info.get("asset_url") or ""
        if not url:
            QDesktopServices.openUrl(QUrl(info["url"])); return
        updates_dir = EXPORT_DIR / "updates"
        try:
            updates_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        fname = url.split("/")[-1] or f"PitBossR3E-Setup-{info.get('version','')}.exe"
        dest = str(updates_dir / fname)
        dlg = QProgressDialog("Lade Update …", "Abbrechen", 0, 100, self)
        dlg.setWindowTitle("Update"); dlg.setAutoClose(False); dlg.setAutoReset(False); dlg.setValue(0)
        self._upd_worker = UpdateDownloadWorker(url, dest)

        def on_prog(d, t):
            dlg.setValue(int(d * 100 / t) if t else 0)

        def on_done(path, err):
            dlg.close()
            if err or not path:
                QMessageBox.warning(self, "Update", f"Download fehlgeschlagen: {err}\n\nIch öffne die Download-Seite.")
                QDesktopServices.openUrl(QUrl(info["url"])); return
            try:
                self.log.append(f"Update geladen: {path}. Starte Installer – App wird beendet.")
                if hasattr(os, "startfile"):
                    os.startfile(path)  # type: ignore[attr-defined]
                else:
                    import subprocess; subprocess.Popen([path])
            except Exception as e:
                QMessageBox.warning(self, "Update", f"Installer-Start fehlgeschlagen: {e}\nDatei liegt in exports/updates.")
                return
            QApplication.quit()

        self._upd_worker.progress.connect(on_prog)
        self._upd_worker.finished_result.connect(on_done)
        dlg.canceled.connect(self._upd_worker.requestInterruption)
        self._upd_worker.start()
        dlg.exec()

    def toggle_pedal_overlay(self):
        if self.pedal_overlay_window is None:
            self.pedal_overlay_window = PedalOverlayWindow()
            try:
                self.pedal_overlay_window.apply_overlay_style(getattr(self, "overlay_style", "transparent"))  # 0.4.9.1
            except Exception:
                pass
        if self.pedal_overlay_window.isVisible():
            self.pedal_overlay_window.hide()
            self.log.append("Pedal-Overlay ausgeblendet.")
        else:
            self.pedal_overlay_window.update_from_main(self)
            self.pedal_overlay_window.show()
            self.pedal_overlay_window.raise_()
            self.log.append("Pedal-Overlay geoeffnet. Zeigt Roh-Input (Gas/Bremse/Kupplung).")

    def _setup_file_logging(self):
        """0.4.8.8: spiegelt alle Log-Zeilen automatisch in eine Datei unter
        exports/logs und faengt unerwartete Fehler ab. Behaelt die letzten 20 Logs."""
        import sys as _sys, glob as _glob, os as _os
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            existing = sorted(_glob.glob(str(LOG_DIR / "pitboss_r3e_*.log")))
            for old in existing[:-19]:
                try: _os.remove(old)
                except Exception: pass
            path = LOG_DIR / f"pitboss_r3e_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            self._logfile = open(path, "a", encoding="utf-8", buffering=1)
            self._logfile.write(f"=== PitBoss R3E {APP_VERSION} – {datetime.now().isoformat(timespec='seconds')} ===\n")
            _orig_append = self.log.append
            def _tee(msg, _o=_orig_append):
                try:
                    self._logfile.write(f"{datetime.now().strftime('%H:%M:%S')}  {msg}\n")
                except Exception:
                    pass
                _o(msg)
            self.log.append = _tee
            _prev_hook = _sys.excepthook
            def _hook(et, ev, tb, _p=_prev_hook):
                try:
                    import traceback as _tbm
                    self._logfile.write("!! UNCAUGHT " + "".join(_tbm.format_exception(et, ev, tb)) + "\n")
                except Exception:
                    pass
                _p(et, ev, tb)
            _sys.excepthook = _hook
            self.log.append(f"Logdatei: {path}")
        except Exception:
            pass

    def _toggle_simple_overlay(self, attr, cls, name):
        win = getattr(self, attr, None)
        if win is None:
            win = cls(); setattr(self, attr, win)
            try:
                win.apply_overlay_style(getattr(self, "overlay_style", "transparent"))
            except Exception:
                pass
        if win.isVisible():
            win.hide(); self.log.append(f"{name} ausgeblendet.")
        else:
            win.update_from_main(self); win.show(); win.raise_()
            self.log.append(f"{name} geoeffnet.")

    def update_sector_times(self, s):
        """0.4.9.0: echte Sektorzeiten des Spiels auswerten (S2 kommt kumuliert)."""
        try:
            secs = self.sector_tracker.on_sample(s)
        except Exception:
            return
        t = self.sector_tracker
        if secs is not None:
            best = t.best
            marks = ["*" if abs(secs[i] - best[i]) < 1e-6 else "" for i in range(3)]
            self.log.append("Sektoren Lap {}: S1 {:.3f}{}  S2 {:.3f}{}  S3 {:.3f}{}  =  {}".format(
                int(getattr(s, "lap_number", 0) or 0) - 1,
                secs[0], marks[0], secs[1], marks[1], secs[2], marks[2],
                fmt_lap_time(sum(secs))))
        if getattr(self, "sector_label", None) is None:
            return
        if t.best_lap <= 0:
            return
        tb = t.theoretical_best()
        txt = ("Sektoren – letzte: S1 {:.3f} · S2 {:.3f} · S3 {:.3f}   |   "
               "beste: S1 {:.3f} · S2 {:.3f} · S3 {:.3f}").format(
            t.last[0], t.last[1], t.last[2], t.best[0], t.best[1], t.best[2])
        if tb > 0:
            txt += "   |   theoretische Bestrunde {}  (beste gefahren {}, Potenzial {:.3f} s)".format(
                fmt_lap_time(tb), fmt_lap_time(t.best_lap), max(t.best_lap - tb, 0.0))
        self.sector_label.setText(txt)

    def update_brake_status(self):
        """0.4.9.4: Bremstemperatur/-verschleiss auch ohne offenes Overlay im
        Hauptfenster zeigen (der Verschleiss ist eine Schaetzung aus 0.4.9.2)."""
        lab = getattr(self, "brake_status_label", None)
        if lab is None:
            return
        m = getattr(self, "brake_model", None)
        if m is None:
            return
        temps = m.temps_c()
        if not any(t is not None for t in temps):
            return
        names = ["VL", "VR", "HL", "HR"]
        parts = []
        for i in range(4):
            t = temps[i]
            parts.append(f"{names[i]} {t:.0f}\u00b0C / {m.wear_pct(i):.0f} %" if t is not None else f"{names[i]} \u2014")
        txt = ("Bremsen (Temp / Verschlei\u00df gesch\u00e4tzt): "
               + "  \u00b7  ".join(parts))
        if m.fading_risk():
            txt += "   \u2013 FADING-GEFAHR"
        lab.setText(txt)

    def set_coach_lead(self, kind):
        """0.4.9.8: Vorlauf der Sprachansage einstellen. Groesserer Wert =
        frueher angesagt. Wert gilt ab sofort und wird gespeichert."""
        from PySide6.QtWidgets import QInputDialog
        names = {"brake": "Bremsen", "turnin": "Einlenken", "gas": "Gas"}
        cur = self.brake_coach.get_lead(kind)
        val, ok = QInputDialog.getDouble(
            self, f"Ansage-Vorlauf: {names.get(kind, kind)}",
            f"Sekunden VOR dem Punkt ansagen (h\u00f6her = fr\u00fcher).\n"
            f"Aktuell: {cur:.2f} s   \u00b7   Bereich 0,0 \u2013 3,0 s",
            cur, 0.0, 3.0, 2, 0.05)
        if not ok:
            return
        self.brake_coach.set_lead(kind, val)
        self.log.append(f"Ansage-Vorlauf {names.get(kind, kind)}: {val:.2f} s "
                        f"(gespeichert in exports/coach_timing.json).")
        self.status.setText(f"Vorlauf {names.get(kind, kind)} = {val:.2f} s")

    def set_coach_lead_all(self):
        """0.5.8.0: Ansage-Vorlauf fuer Bremsen/Einlenken/Gas in EINEM Dialog mit
        drei Schiebereglern (0,00-3,00 s, hoeher = frueher). Loest die drei
        einzelnen Popups ab. Sofort wirksam, gespeichert in coach_timing.json."""
        from PySide6.QtWidgets import (QDialog, QSlider, QVBoxLayout, QHBoxLayout,
                                       QLabel, QDialogButtonBox, QWidget)
        from PySide6.QtCore import Qt as _Qt
        bc = self.brake_coach
        specs = [("brake", "Bremsen"), ("turnin", "Einlenken"), ("gas", "Gas")]
        dlg = QDialog(self)
        dlg.setWindowTitle("Ansage-Vorlauf")
        lay = QVBoxLayout(dlg)
        intro = QLabel("Sekunden VOR dem Punkt ansagen (h\u00f6her = fr\u00fcher).\n"
                       "Bereich 0,00 \u2013 3,00 s.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        sliders = {}
        for key, name in specs:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
            cap = QLabel(name); cap.setMinimumWidth(90)
            sld = QSlider(_Qt.Horizontal)
            sld.setMinimum(0); sld.setMaximum(60)  # x 0,05 s = 0..3,00 s
            sld.setSingleStep(1); sld.setPageStep(2)
            sld.setValue(int(round(bc.get_lead(key) / 0.05)))
            val = QLabel(); val.setMinimumWidth(56)
            sld.valueChanged.connect(
                (lambda lbl: (lambda v: lbl.setText(f"{v * 0.05:.2f} s")))(val))
            val.setText(f"{sld.value() * 0.05:.2f} s")
            rl.addWidget(cap); rl.addWidget(sld, 1); rl.addWidget(val)
            lay.addWidget(row)
            sliders[key] = sld
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        for key, name in specs:
            bc.set_lead(key, round(sliders[key].value() * 0.05, 2))
        self.log.append("Ansage-Vorlauf gesetzt: "
                        + ", ".join(f"{n} {bc.get_lead(k):.2f}s" for k, n in specs)
                        + " (exports/coach_timing.json).")
        self.status.setText("Ansage-Vorlauf aktualisiert.")

    def calibrate_brake_model(self):
        """0.4.9.2: Modell an einen real beobachteten Verschleiss anpassen."""
        from PySide6.QtWidgets import QInputDialog
        cur = self.brake_model.worst_wear()
        val, ok = QInputDialog.getDouble(
            self, "Bremsmodell kalibrieren",
            f"Das Modell schaetzt aktuell {cur:.1f} % am staerksten belasteten Rad.\n"
            "Wie hoch war der tatsaechliche Verschleiss in Prozent?",
            cur if cur > 0 else 10.0, 0.1, 100.0, 1)
        if not ok:
            return
        if self.brake_model.calibrate_to(val):
            self.log.append(f"Bremsmodell kalibriert: {cur:.1f} % entsprechen jetzt {val:.1f} %. "
                            f"Gespeichert in exports/brake_model.json.")
        else:
            self.log.append("Kalibrierung nicht moeglich - erst ein paar Bremsungen fahren.")

    def toggle_pit_overlay(self):
        self._toggle_simple_overlay("pit_overlay_window", PitOverlayWindow, "Pit-Overlay")

    def toggle_delta_overlay(self):
        self._toggle_simple_overlay("delta_overlay_window", DeltaOverlayWindow, "Delta-Overlay")

    def toggle_laptime_overlay(self):
        self._toggle_simple_overlay("laptime_overlay_window", LapTimeOverlayWindow, "Rundenzeiten-Overlay")

    def toggle_damage_overlay(self):
        self._toggle_simple_overlay("damage_overlay_window", DamageOverlayWindow, "Schaden-Overlay")

    def maybe_autoshow_flag_overlay(self, s):
        # 0.5.5.0: Flaggen-Overlay nur zeigen, wenn das Spiel eine echte Flagge meldet
        # (gelb/blau/weiss/rot/kariert). Gruen oder keine Flagge -> ausblenden.
        if not getattr(self, "flag_overlay_armed", False):
            return
        try:
            flag, _lbl = FlagOverlayWindow._decide(s)
        except Exception:
            flag = "none"
        real = flag not in ("green", "none")
        win = getattr(self, "flag_overlay_window", None)
        if real:
            if win is None:
                win = FlagOverlayWindow(); self.flag_overlay_window = win
                try:
                    win.apply_overlay_style(getattr(self, "overlay_style", "transparent"))
                except Exception:
                    pass
            win.update_from_main(self)
            if not win.isVisible():
                win.show(); win.raise_()
        elif win is not None and win.isVisible():
            win.hide()

    def toggle_flag_overlay(self):
        # 0.5.5.0: schaltet die automatische Flaggen-Anzeige scharf/aus.
        self.flag_overlay_armed = not getattr(self, "flag_overlay_armed", False)
        if self.flag_overlay_armed:
            self.log.append("Flaggen-Overlay scharf: erscheint automatisch, sobald das Spiel eine Flagge zeigt.")
        else:
            w = getattr(self, "flag_overlay_window", None)
            if w is not None and w.isVisible():
                w.hide()
            self.log.append("Flaggen-Overlay aus.")

    def toggle_lapgraph_overlay(self):
        self._toggle_simple_overlay("lapgraph_overlay_window", LapGraphOverlayWindow, "Rundenzeiten-Graph")

    def toggle_overtake_overlay(self):
        self._toggle_simple_overlay("overtake_overlay_window", OvertakeOverlayWindow, "Überholalarm")

    def toggle_blindspot_overlay(self):  # 0.5.9.13
        self._toggle_simple_overlay("blindspot_overlay_window", BlindSpotOverlayWindow, "Toter-Winkel-Overlay")

    def set_blindspot_flip(self, on):  # 0.5.9.13
        on = bool(on)
        win = getattr(self, "blindspot_overlay_window", None)
        if win is not None:
            win.set_flip(on)
        else:
            try:
                EXPORT_DIR.mkdir(parents=True, exist_ok=True)
                BLINDSPOT_CONFIG_PATH.write_text(json.dumps({"flip": on}), encoding="utf-8")
            except Exception:
                pass
        try:
            self.status.setText("Toter Winkel: Seiten " + ("gespiegelt." if on else "normal."))
        except Exception:
            pass

    def all_overlay_windows(self):
        """0.4.9.1: alle Overlay-Fenster, die es aktuell gibt."""
        out = []
        for a in ("overlay_window", "tire_overlay_window", "pedal_overlay_window",
                  "limit_overlay_window", "brake_overlay_window",
                  "fuel_overlay_window", "ffb_overlay_window", "pit_overlay_window",
                  "delta_overlay_window", "laptime_overlay_window", "damage_overlay_window",
                  "flag_overlay_window", "lapgraph_overlay_window", "overtake_overlay_window",
                  "blindspot_overlay_window",
                  "corner_name_overlay_window"):
            w = getattr(self, a, None)
            if w is not None:
                out.append(w)
        return out

    def overlay_style_path(self):
        return str(EXPORT_DIR / "overlay_style.txt")

    def load_overlay_style(self):
        try:
            with open(self.overlay_style_path(), "r", encoding="utf-8") as f:
                v = f.read().strip()
            return v if v in ("transparent", "dark", "light") else "transparent"
        except Exception:
            return "transparent"

    def set_overlay_style(self, mode):
        """0.4.9.1: Stil auf ALLE Overlays anwenden und merken."""
        self.overlay_style = mode if mode in ("transparent", "dark", "light") else "transparent"
        for w in self.all_overlay_windows():
            try:
                w.apply_overlay_style(self.overlay_style)
            except Exception:
                pass
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.overlay_style_path(), "w", encoding="utf-8") as f:
                f.write(self.overlay_style)
        except Exception:
            pass
        for key, act in getattr(self, "overlay_style_actions", {}).items():
            try:
                act.setChecked(key == self.overlay_style)
            except Exception:
                pass
        self.log.append(f"Overlay-Design: {self.overlay_style}.")

    def maybe_autoshow_pit_overlay(self, s):
        """0.4.9.1: Pit-Overlay automatisch beim Einfahren zeigen und beim
        Verlassen wieder schliessen (nur wenn es automatisch geoeffnet wurde)."""
        try:
            in_pit = bool(getattr(s, "in_pits", False)) or int(getattr(s, "pit_state", 0) or 0) in (1, 2, 3, 4)
        except Exception:
            return
        win = self.pit_overlay_window
        if in_pit:
            if win is None:
                win = PitOverlayWindow(); self.pit_overlay_window = win
                win.apply_overlay_style(self.overlay_style)
            if not win.isVisible():
                win.auto_opened = True
                win.update_from_main(self); win.show(); win.raise_()
                self.log.append("Boxengasse erkannt \u2013 Pit-Overlay automatisch geoeffnet.")
        elif win is not None and win.isVisible() and getattr(win, "auto_opened", False):
            win.hide(); win.auto_opened = False
            self.log.append("Boxengasse verlassen \u2013 Pit-Overlay automatisch geschlossen.")

    def toggle_brake_overlay(self):
        self._toggle_simple_overlay("brake_overlay_window", BrakeTempOverlayWindow, "Bremstemperatur-Overlay")

    def toggle_fuel_overlay(self):
        self._toggle_simple_overlay("fuel_overlay_window", FuelOverlayWindow, "Sprit-Overlay")

    def toggle_ffb_overlay(self):
        self._toggle_simple_overlay("ffb_overlay_window", FFBOverlayWindow, "FFB-Overlay (Doppelklick = Statistik zuruecksetzen)")

    def toggle_limit_overlay(self):
        if self.limit_overlay_window is None:
            self.limit_overlay_window = LimitOverlayWindow()
            try:
                self.limit_overlay_window.apply_overlay_style(getattr(self, "overlay_style", "transparent"))  # 0.4.9.1
            except Exception:
                pass
        if self.limit_overlay_window.isVisible():
            self.limit_overlay_window.hide()
            self.log.append("Limit-Meter ausgeblendet.")
        else:
            self.limit_overlay_window.update_from_main(self)
            self.limit_overlay_window.show()
            self.limit_overlay_window.raise_()
            self.log.append("Limit-Meter geoeffnet. Grip-Kreis aus mLocalAccel; Doppelklick = Kalibrierung zuruecksetzen. Push eine harte Kurve/Bremsung zum Kalibrieren.")

    def toggle_overlay(self):
        if self.overlay_window is None:
            self.overlay_window = OverlayWindow()
            try:
                self.overlay_window.apply_overlay_style(getattr(self, "overlay_style", "transparent"))  # 0.4.9.1
            except Exception:
                pass
        self.cleanup_duplicate_overlays()
        if self.overlay_window.isVisible():
            self.overlay_window.hide()
            self.log.append("Monitor-Overlay ausgeblendet.")
        else:
            self.cleanup_duplicate_overlays()
            self.overlay_window.update_from_main(self)
            self.overlay_window.show()
            self.overlay_window.raise_()
            self.log.append("Monitor-Overlay geöffnet. Singleton aktiv: nur ein Coach-Overlay; Reifen-Overlay bleibt separat möglich.")

    def refresh_overlay(self):
        if self.overlay_window is not None and self.overlay_window.isVisible():
            self.overlay_window.update_from_main(self)
        if self.tire_overlay_window is not None and self.tire_overlay_window.isVisible():
            self.tire_overlay_window.update_from_main(self)
        if self.pedal_overlay_window is not None and self.pedal_overlay_window.isVisible():
            self.pedal_overlay_window.update_from_main(self)
        if self.limit_overlay_window is not None and self.limit_overlay_window.isVisible():
            self.limit_overlay_window.update_from_main(self)
        for _a in ("brake_overlay_window",
                   "fuel_overlay_window", "ffb_overlay_window",
                   "pit_overlay_window", "delta_overlay_window",
                   "laptime_overlay_window", "damage_overlay_window",
                   "flag_overlay_window", "lapgraph_overlay_window", "overtake_overlay_window",
                   "blindspot_overlay_window"):
            _w = getattr(self, _a, None)
            if _w is not None and _w.isVisible():
                _w.update_from_main(self)

    def set_dash_card(self, key: str, value: str):
        if hasattr(self, "dash_cards") and key in self.dash_cards:
            self.dash_cards[key].setText(value)

    def current_best_lap_time_s(self) -> float:
        best = self.sim_best_lap_from_scoring() if self.samples else 0.0
        if best > 0:
            return best
        clean = [self.lap_time_for_report(l) for l in self.lap_summaries if l.is_clean and self.lap_time_for_report(l) > 0]
        return min(clean) if clean else 0.0

    # ------------------------------------------------------------------
    # 0.2.0: UI-Aktualisierung entkoppelt vom Aufnahme-Takt.
    # Frueher lief bei jedem Snapshot (10 Hz) ein komplettes Dashboard-Refresh
    # inkl. Coach-Texten, Tabellen und Trackmap. Jetzt: ein 2-Hz-Takt, der nur
    # die SICHTBARE Ansicht aktualisiert (und gar nichts, wenn das Fenster
    # minimiert/verdeckt ist). Schwere Texte werden nur bei echten Ereignissen
    # (Analyse, Profil, Referenz) oder beim Tabwechsel neu gebaut.
    # ------------------------------------------------------------------
    def refresh_dashboard(self):
        """Ereignis-getrieben: Analyse/Profil/Referenz haben sich geaendert."""
        self._heavy_dirty = True
        self._refresh_visible_view()

    def _on_tab_changed(self, _idx=0):
        self._heavy_dirty = True
        self._refresh_visible_view()

    def _view_tick(self):
        if not self.isVisible() or self.isMinimized():
            return
        self._update_conn_pill()
        self._refresh_visible_view(live_only=True)

    def _update_conn_pill(self):
        ok_ts = getattr(self, "_last_read_ok_ts", 0.0)
        connected = (time.monotonic() - ok_ts) < 2.5 if ok_ts else False
        if self.recording:
            state, text = "rec", "\u25cf  AUFNAHME L\u00c4UFT"
        elif connected:
            state, text = "on", "\u25cf  RACEROOM VERBUNDEN"
        else:
            # 0.2.39: Fehlergrund auf der Kopfleiste mitzeigen (kurz, einordnend)
            _err = getattr(self, "_live_err", None)
            _hint = " \u2013 " + _err if _err else ""
            if len(_hint) > 60:
                _hint = _hint[:57] + "..."
            state, text = "off", "WARTET AUF RACEROOM" + _hint
        pill = self.conn_pill
        if pill.property("state") != state:
            pill.setProperty("state", state)
            pill.style().unpolish(pill); pill.style().polish(pill)
        if pill.text() != text:
            pill.setText(text)

    def _set_rec_ui(self, on: bool):
        self.btn_record.setText("\u25a0  AUFNAHME STOPPEN" if on else "\u25cf  AUFNAHME STARTEN")
        self.btn_record.setProperty("rec", bool(on))
        self.btn_record.style().unpolish(self.btn_record); self.btn_record.style().polish(self.btn_record)

    def _refresh_visible_view(self, live_only=False):
        try:
            name = self.tabs.tabText(self.tabs.currentIndex())
        except Exception:
            return
        s = self.last_live_sample or (self.samples[-1] if self.samples else None)
        if name == "Dashboard":
            if getattr(self, "_heavy_dirty", True) and not live_only:
                self._heavy_dirty = False
                self._update_dash_heavy()
            self._update_dash_cards(s)
        elif name == "Live":
            if s is not None:
                self._fill_live_summary(s)
            self._tm_tick = getattr(self, "_tm_tick", 0) + 1
            if self.recording and self._tm_tick % 4 == 0 and len(self.samples) != getattr(self, "_tm_len", -1):
                self._tm_len = len(self.samples)
                self.trackmap.set_samples(self.samples)
                self.trackmap.set_sector_info(self.official_sector_bounds())  # 0.2.9
            # 0.2.21: Telemetrie-Reiter live aktualisieren (~alle 2 s)
            self._tele_tick = getattr(self, "_tele_tick", 0) + 1
            if self._tele_tick % 20 == 0 and hasattr(self, "telemetry_trace"):
                try:
                    self.update_telemetry_view()
                except Exception:
                    pass
        elif name == "Reifen":
            if s is not None:
                self.update_tire_table(s)
        elif name == "Coach":
            if getattr(self, "_heavy_dirty", True) and not live_only:
                self._heavy_dirty = False
                self._update_coach_views()

    def _update_dash_cards(self, last):
        _lw = getattr(self.reader, "layout_warning", "") if last else ""
        ok_ts = getattr(self, "_last_read_ok_ts", 0.0)
        connected = bool(last) and ((time.monotonic() - ok_ts) < 2.5 if ok_ts else bool(self.samples))
        if connected:
            _conn = "RaceRoom verbunden" + (" \u2013 API-Hinweis: " + _lw if _lw else "")
        else:
            # 0.2.39: konkreter Fehlergrund statt nur "Wartet auf RaceRoom"
            _err = getattr(self, "_live_err", None)
            _conn = "Wartet auf RaceRoom" + (" \u2013 " + _err if _err else "")
        self.set_dash_card("Verbindung", _conn)
        self.set_dash_card("Recording", "\U0001f534 L\u00c4UFT" if self.recording else "gestoppt")
        clean = [l for l in self.lap_summaries if l.is_clean]
        self.set_dash_card("Runden", f"{len(clean)} g\u00fcltig / {len(self.lap_summaries)} erkannt" if self.lap_summaries else "noch keine Analyse")
        ref_text = self.reference_display_label(short=True) if self.reference_lap or self.external_reference else "Auto / offen"
        if self.external_reference:
            ref_text += " (extern, aktiv)" if self.use_external_reference else " (extern, geladen)"
        if self.auto_bestlap_export_path:
            ref_text += f"  \u00b7  Auto-Bestlap Lap {self.auto_bestlap_lap_number} {fmt_lap_time(self.auto_bestlap_time_s)}"
        self.set_dash_card("Referenz", ref_text)
        if last:
            tire_txt = f"VL/VR {last.tire_fl_pressure_kpa:.0f}/{last.tire_fr_pressure_kpa:.0f} kPa  \u00b7  HL/HR {last.tire_rl_pressure_kpa:.0f}/{last.tire_rr_pressure_kpa:.0f} kPa"
        else:
            tire_txt = "noch keine Daten"
        self.set_dash_card("Reifen", tire_txt)
        self.set_dash_card("Coach-Fokus", getattr(self, "_dash_focus_txt", "nach Rundenvergleich"))

    def _update_dash_heavy(self):
        zones = self.grouped_problem_zones() if self.segment_deltas else []
        if zones:
            z = zones[0]
            self._dash_focus_txt = f"Zone 1 | {z[0]}-{z[1]} m ({self.sector_name_for_m(z[0]) or '?'}) | {z[2]:+.3f} s"
        else:
            self._dash_focus_txt = "nach Rundenvergleich"
        lines = self.coach_report_lines()
        keep = [ln for ln in lines if ln.startswith(("Vergleich", "Zone 1", "Zone 2", "Kurzfazit", "Der gr\u00f6\u00dfte"))]
        self.dash_coach.setPlainText("\n".join(keep) if keep else "Nach Recording-Stopp erscheinen hier die wichtigsten Coach-Hinweise.")

    def _update_coach_views(self):
        sc_lines = self.tire_setup_coach_lines()
        self.setup_coach_text.setPlainText("\n".join(sc_lines) if sc_lines else "Noch keine Reifen-/Setup-Daten.")
        lc_lines = self.limit_coach_report_lines(summary_only=False)
        self.limit_coach_text.setPlainText("\n".join(lc_lines) if lc_lines else "Noch keine Limit-Daten.")
        if self.samples and self.lap_summaries:
            ic_lines = self.input_coach_report_lines(summary_only=True)
            self.input_coach_text.setPlainText("\n".join(ic_lines) if ic_lines else "Nach Recording-Stopp erscheinen hier Gas-/Brems-Hinweise.")

    def selected_setup_label(self) -> str:
        try:
            txt = self.setup_selector.currentText().strip()
        except Exception:
            txt = ""
        return txt or "nicht gesetzt"

    def current_context(self):
        s = self.samples[-1] if self.samples else None
        if s:
            return s.track, infer_vehicle_class(s.vehicle_class, s.vehicle_name, s.vehicle_model), s.vehicle_name
        return "", "Unbekannt", ""

    def external_reference_label(self, short: bool = False) -> str:
        if not self.external_reference:
            return "nicht geladen"
        m = self.external_reference.get("meta", {})
        lap_time = m.get("lap_time_s")
        time_txt = fmt_lap_time(lap_time) if isinstance(lap_time, (int, float)) else "-"
        if short:
            return f"{m.get('track','?')} | {m.get('vehicle_class','?')} | {time_txt}"
        return f"{m.get('track','?')} | {m.get('vehicle_class','?')} | {m.get('vehicle_name','?')} | {time_txt}"

    def reference_display_label(self, short: bool = False) -> str:
        if self.external_reference and self.use_external_reference:
            return "Extern: " + self.external_reference_label(short=short)
        if self.reference_lap:
            return f"Lap {self.reference_lap.lap_number}"
        return "Auto / offen"

    def segment_to_dict(self, seg: SegmentSummary) -> dict:
        return {
            "lap_number": seg.lap_number, "start_m": seg.start_m, "end_m": seg.end_m,
            "samples": seg.samples, "seg_time_s": seg.seg_time_s, "avg_speed": seg.avg_speed,
            "min_speed": seg.min_speed, "max_speed": seg.max_speed, "max_brake": seg.max_brake,
            "avg_throttle": seg.avg_throttle, "gear_common": seg.gear_common,
        }

    def dict_to_segment(self, d: dict) -> SegmentSummary:
        return SegmentSummary(
            lap_number=int(d.get("lap_number", -1)), start_m=int(d.get("start_m", 0)), end_m=int(d.get("end_m", 50)),
            samples=int(d.get("samples", 0)), seg_time_s=fnum(d.get("seg_time_s")), avg_speed=fnum(d.get("avg_speed")),
            min_speed=fnum(d.get("min_speed")), max_speed=fnum(d.get("max_speed")), max_brake=fnum(d.get("max_brake")),
            avg_throttle=fnum(d.get("avg_throttle")), gear_common=str(d.get("gear_common", "-")),
        )


    def set_auto_bestlap_ui(self):
        state = "AN" if self.auto_bestlap_export_enabled else "AUS"
        self.btn_auto_bestlap.setText(f"Auto-Bestlap: {state}")
        self.btn_auto_bestlap.setToolTip(self.hotkey_config.get("auto_bestlap", "F7") + ": Auto-Bestlap AN/AUS")
        _act = getattr(self, "act_auto_bestlap", None)
        if _act is not None:
            _act.setChecked(bool(self.auto_bestlap_export_enabled))
        self.status.setText(f"Auto-Bestlap {state}.")

    def toggle_live_log(self):  # 0.5.9.26
        if self.live_log_enabled:
            self.stop_live_log()
        else:
            self.start_live_log()

    def start_live_log(self):  # 0.5.9.26
        try:
            CSV_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = CSV_DIR / f"live_log_{ts}.csv"
            fh = open(path, "w", newline="", encoding="utf-8")
            fieldnames = [f.name for f in _dc_fields(Sample)]
            writer = csv.writer(fh)
            writer.writerow(fieldnames)
            self.live_log_fh = fh
            self.live_log_writer = writer
            self.live_log_path = path
            self.live_log_row_count = 0
            self.live_log_enabled = True
            self.btn_live_log.setText("Live-Log: AN")
            self.log.append(f"Live-Log gestartet: {path.name} (unabhaengig vom Recording, jeder Live-Tick wird mitgeschrieben).")
        except Exception as e:
            self.live_log_enabled = False
            QMessageBox.warning(self, "Live-Log", f"Live-Log konnte nicht gestartet werden:\n{e}")

    def stop_live_log(self):  # 0.5.9.26
        self.live_log_enabled = False
        self.btn_live_log.setText("Live-Log: AUS")
        path, n = self.live_log_path, self.live_log_row_count
        try:
            if self.live_log_fh is not None:
                self.live_log_fh.flush()
                self.live_log_fh.close()
        except Exception:
            pass
        self.live_log_fh = None
        self.live_log_writer = None
        if path is not None:
            self.log.append(f"Live-Log gestoppt: {n} Zeilen in {path}")

    def write_live_log_row(self, s: Sample):  # 0.5.9.26
        if not self.live_log_enabled or self.live_log_writer is None:
            return
        try:
            self.live_log_writer.writerow(_dc_astuple(s))
            self.live_log_row_count += 1
            if self.live_log_row_count % 20 == 0:  # ~alle 2s flushen, Datenverlust bei Absturz begrenzen
                self.live_log_fh.flush()
        except Exception as e:
            self.log.append(f"Live-Log-Fehler, wird gestoppt: {e}")
            self.stop_live_log()

    def toggle_auto_bestlap_export(self):
        self.auto_bestlap_export_enabled = not self.auto_bestlap_export_enabled
        self.set_auto_bestlap_ui()
        self.log.append("Auto-Bestlap-Export " + ("aktiviert" if self.auto_bestlap_export_enabled else "deaktiviert"))
        self.refresh_dashboard()

    def set_auto_switch_ui(self):  # 0.5.9.24
        state = "AN" if self.auto_switch_recording_enabled else "AUS"
        self.btn_auto_switch.setText(f"Auto-Wechsel: {state}")
        _act = getattr(self, "act_auto_switch", None)
        if _act is not None:
            _act.setChecked(bool(self.auto_switch_recording_enabled))
        self.btn_auto_switch.setToolTip(
            "Bei Strecken-/Fahrzeugwechsel während der Aufnahme automatisch stoppen "
            "(Report/CSV speichern) und für den neuen Kontext neu starten."
        )

    def toggle_auto_switch_recording(self):  # 0.5.9.24
        self.auto_switch_recording_enabled = not self.auto_switch_recording_enabled
        self.set_auto_switch_ui()
        self.log.append("Auto-Wechsel-Neustart " + ("aktiviert" if self.auto_switch_recording_enabled else "deaktiviert"))

    def toggle_auto_bestlap_hotkey(self):
        # F7 kann durch Stream Deck + App-Shortcut + Windows-Polling doppelt feuern.
        # Debounce verhindert AN+AUS im selben Tastendruck.
        now = datetime.now().timestamp()
        if now - getattr(self, "last_auto_hotkey_ts", 0.0) < 0.8:
            self.log.append("F7 ignoriert: Tastendruck-Doppelung verhindert.")
            return
        self.last_auto_hotkey_ts = now
        self.toggle_auto_bestlap_export()

    def snapshot_hotkey(self):
        # Auch F9 kann je nach Stream Deck Profil doppelt feuern.
        now = datetime.now().timestamp()
        if now - getattr(self, "last_snapshot_hotkey_ts", 0.0) < 0.8:
            self.log.append("F9 ignoriert: Tastendruck-Doppelung verhindert.")
            return
        self.last_snapshot_hotkey_ts = now
        self.snapshot(silent=False)

    def toggle_tire_overlay_hotkey(self):
        # F6: separates Reifen-Overlay. Debounce gegen Stream-Deck/Key-Repeat.
        now = datetime.now().timestamp()
        if now - getattr(self, "last_tire_overlay_hotkey_ts", 0.0) < 1.0:
            self.log.append("F6 ignoriert: Tastendruck-Doppelung verhindert.")
            return
        self.last_tire_overlay_hotkey_ts = now
        self.cleanup_duplicate_tire_overlays()
        self.toggle_tire_overlay()

    def setup_hotkeys(self):
        # Unter Windows nutzen wir ausschließlich den Polling-Hotkey.
        # Sonst feuern QShortcut + GetAsyncKeyState parallel und Stream Deck kann doppelt auslösen
        # oder Overlay-Fenster scheinbar doppelt öffnen.
        # 0.2.5: Die Tasten kommen aus der frei belegbaren Konfiguration (hotkeys.json).
        for _attr in ("shortcut_tire_overlay", "shortcut_auto_bestlap", "shortcut_record",
                      "shortcut_snapshot", "shortcut_overlay", "shortcut_live_coach",
                      "shortcut_brake_coach",
                      "shortcut_corner_overlay"):
            _old = getattr(self, _attr, None)
            if _old is not None:
                try:
                    _old.deleteLater()
                except Exception:
                    pass
        if sys.platform.startswith("win"):
            self.shortcut_tire_overlay = None
            self.shortcut_auto_bestlap = None
            self.shortcut_record = None
            self.shortcut_snapshot = None
            self.shortcut_overlay = None
            self.shortcut_live_coach = None
            self.shortcut_brake_coach = None
            self.log.append("App-Hotkeys unter Windows deaktiviert: nutze nur Windows-Global-Polling gegen Doppeltrigger. " + self.hotkey_config.get("tire_overlay", "F6") + "=Reifen-Overlay.")
            return

        bindings = [
            ("shortcut_tire_overlay", "tire_overlay", self.toggle_tire_overlay_hotkey),
            ("shortcut_auto_bestlap", "auto_bestlap", self.toggle_auto_bestlap_hotkey),
            ("shortcut_record", "record", self.toggle_recording_hotkey),
            ("shortcut_snapshot", "snapshot", self.snapshot_hotkey),
            ("shortcut_overlay", "overlay", self.toggle_overlay_hotkey),
            ("shortcut_live_coach", "live_coach", self.toggle_live_coach_hotkey),
            ("shortcut_brake_coach", "brake_coach", self.toggle_brake_coach_hotkey),
            ("shortcut_corner_overlay", "corner_overlay", self.toggle_corner_name_overlay),
        ]
        for attr, action, handler in bindings:
            sc = QShortcut(QKeySequence(self.hotkey_config.get(action, DEFAULT_HOTKEYS[action])), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(handler)
            setattr(self, attr, sc)
        self.log.append("App-Hotkeys aktiv: " + hotkey_summary(self.hotkey_config))

    def toggle_recording_hotkey(self):
        # F8 kann bei Windows/Stream Deck durch Key-Repeat doppelt auslösen.
        # Kurzer Debounce verhindert direktes Start+Stop im selben Tastendruck.
        now = datetime.now().timestamp()
        if now - getattr(self, "last_record_hotkey_ts", 0.0) < 0.8:
            self.log.append("F8 ignoriert: Tastendruck-Doppelung verhindert.")
            return
        self.last_record_hotkey_ts = now
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def toggle_overlay_hotkey(self):
        # F10 kann durch App-Shortcut + Windows-Polling doppelt feuern.
        # Debounce verhindert Show+Hide im selben Tastendruck.
        now = datetime.now().timestamp()
        if now - getattr(self, "last_overlay_hotkey_ts", 0.0) < 1.0:
            self.log.append("F10 ignoriert: Tastendruck-Doppelung verhindert.")
            return
        self.last_overlay_hotkey_ts = now
        self.cleanup_duplicate_overlays()
        self.toggle_overlay()



    def toggle_live_coach_hotkey(self):
        now = datetime.now().timestamp()
        if now - getattr(self, "last_live_coach_hotkey_ts", 0.0) < 0.8:
            return
        self.last_live_coach_hotkey_ts = now
        self.set_live_coach_enabled(not self.live_coach_enabled)
        if getattr(self, "act_live_coach", None) is not None:
            self.act_live_coach.setChecked(self.live_coach_enabled)

    def set_live_coach_enabled(self, on):
        self.live_coach_enabled = bool(on)
        self.live_coach.set_enabled(self.live_coach_enabled)
        if self.live_coach_enabled and not self.tts.is_available():
            self.log.append("Live-Coach an, aber keine Sprachausgabe verfügbar – Piper/SAPI prüfen.")
        if self.live_coach_enabled:
            self._refresh_live_coach_status()
        else:
            self.status.setText("Live-Coach AUS.")

    def toggle_brake_coach_hotkey(self):
        now = datetime.now().timestamp()
        if now - getattr(self, "last_brake_coach_hotkey_ts", 0.0) < 0.8:
            return
        self.last_brake_coach_hotkey_ts = now
        self.set_brake_coach_enabled(not self.brake_coach_enabled)
        if getattr(self, "act_brake_coach", None) is not None:
            self.act_brake_coach.setChecked(self.brake_coach_enabled)

    def set_brake_coach_enabled(self, on):
        self.brake_coach_enabled = bool(on)
        self.brake_coach.set_enabled(self.brake_coach_enabled)
        if self.brake_coach_enabled:
            if not self.tts.is_available():
                self.log.append("Kurven-Coach an, aber keine Sprachausgabe – Piper/SAPI prüfen.")
            elif not self.brake_coach.has_points():
                self.log.append("Kurven-Coach an – noch keine Referenzpunkte. Fahre eine saubere Bestlap.")
            self.status.setText("Kurven-Coach AN – Bremsen/Einlenken/Gas an harten Kurven (F12).")
        else:
            self.status.setText("Kurven-Coach AUS.")

    def setup_windows_global_hotkeys(self):
        """Poll F6-F10 on Windows so Stream Deck / keyboard also work while RaceRoom has focus.
        This avoids requiring a separate global hotkey library.
        """
        self.global_hotkey_timer = None
        if not sys.platform.startswith("win"):
            self.log.append("Globale Windows-Hotkeys nicht aktiv: nicht unter Windows erkannt.")
            return
        try:
            self._user32 = ctypes.windll.user32
            self.global_hotkey_timer = QTimer(self)
            self.global_hotkey_timer.setInterval(60)
            self.global_hotkey_timer.timeout.connect(self.poll_windows_hotkeys)
            self.global_hotkey_timer.start()
            self.log.append("Windows-Global-Hotkeys aktiv: " + "/".join(sorted(set(self.hotkey_config.values()))) + " funktionieren auch wenn RaceRoom im Fokus ist.")
        except Exception as e:
            self.log.append(f"Windows-Global-Hotkeys konnten nicht aktiviert werden: {e}")

    def _vk_down(self, vk: int) -> bool:
        try:
            return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return False

    def poll_windows_hotkeys(self):
        # 0.2.5: Tasten kommen aus der frei belegbaren Hotkey-Konfiguration.
        # VK codes: F1=0x70..F24=0x87, 0=0x30..9=0x39 (siehe hotkey_vk()).
        handlers = {
            "tire_overlay": self.toggle_tire_overlay_hotkey,
            "auto_bestlap": self.toggle_auto_bestlap_hotkey,
            "record": self.toggle_recording_hotkey,
            "snapshot": self.snapshot_hotkey,
            "overlay": self.toggle_overlay_hotkey,
            "live_coach": self.toggle_live_coach_hotkey,
            "brake_coach": self.toggle_brake_coach_hotkey,
            "corner_overlay": self.toggle_corner_name_overlay,
        }
        for action, key in self.hotkey_config.items():
            vk = hotkey_vk(key)
            if vk is None:
                continue
            down = self._vk_down(vk)
            was_down = self.global_hotkey_state.get(key, False)
            if down and not was_down:
                handler = handlers.get(action)
                if handler is not None:
                    handler()
            self.global_hotkey_state[key] = down

    def open_beta_feedback(self):
        """0.2.33: Beta-Tester-Formular fuer Bugs und Aenderungswuensche.
        GitHub-Issue im Browser (empfohlen) oder offline als Datei."""
        dlg = BetaFeedbackDialog(self)
        dlg.exec()

    def open_hotkey_settings(self):
        """0.2.5: Frei belegbare Hotkey-Liste fuer Stream Deck/Tastatur.

        Erlaubt sind F1-F24 und 0-9. Jede Taste darf nur einer Aktion zugeordnet
        sein. Die Belegung wird in Dokumente\\PitBoss R3E\\hotkeys.json gespeichert
        und gilt sofort (Windows-Polling liest sie live, App-Shortcuts werden neu gebaut).
        """
        cfg = dict(self.hotkey_config)
        dlg = QDialog(self)
        dlg.setWindowTitle("Hotkeys belegen")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        info = QLabel("Frei belegbare Hotkeys für Stream Deck/Tastatur. Erlaubt: F1–F24 und 0–9. Jede Taste nur einmal.")
        info.setWordWrap(True)
        layout.addWidget(info)
        combos = {}
        for action, label in HOTKEY_ACTIONS:
            row = QHBoxLayout()
            lab = QLabel(label + ":")
            lab.setMinimumWidth(180)
            row.addWidget(lab)
            combo = QComboBox()
            combo.addItems(SUPPORTED_HOTKEY_KEYS)
            combo.setCurrentText(cfg.get(action, DEFAULT_HOTKEYS[action]))
            combo.setMinimumWidth(120)
            row.addWidget(combo)
            row.addStretch(1)
            layout.addLayout(row)
            combos[action] = combo
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        new_cfg = {action: combos[action].currentText() for action, _label in HOTKEY_ACTIONS}
        used = {}
        for action, key in new_cfg.items():
            if key in used:
                QMessageBox.warning(self, "Hotkeys", f"Taste {key} ist doppelt belegt ({used[key]} und {action}). Nichts gespeichert.")
                return
            used[key] = action
        self.hotkey_config = new_cfg
        if not save_hotkey_config(new_cfg):
            self.log.append("Hotkeys konnten nicht gespeichert werden (Datei nicht schreibbar).")
        self.global_hotkey_state = {k: False for k in new_cfg.values()}
        if not sys.platform.startswith("win"):
            self.setup_hotkeys()  # App-Shortcuts mit neuen Tasten neu bauen
        self.log.append("Hotkeys gespeichert: " + hotkey_summary(new_cfg))
        self.status.setText("Hotkeys gespeichert: " + ", ".join(new_cfg.values()))

    def _stable_timing_value(self, vals: List[float]) -> float:
        """Return the most stable official timing value from RaceRoom scoring rows.

        RaceRoom updates lap_time_previous_self shortly after a lap rollover. On some
        frames the previous value can still be visible for one sample. Taking
        the most common rounded value avoids picking that stale one.
        """
        clean = []
        for v in vals or []:
            try:
                f = float(v)
                if 20.0 <= f <= 1800.0 and math.isfinite(f):
                    clean.append(round(f, 3))
            except Exception:
                pass
        if not clean:
            return 0.0
        counts = {}
        for v in clean:
            counts[v] = counts.get(v, 0) + 1
        # Prefer the value that appears most often; tie-breaker: later value in the list.
        best_count = max(counts.values())
        candidates = [v for v, c in counts.items() if c == best_count]
        for v in reversed(clean):
            if v in candidates:
                return float(v)
        return float(candidates[0])

    def sim_scoring_time_for_lap_from_rows(self, rows: List[Sample], lap_number: int) -> float:
        """0.4.5.2: Official lap time per lap from RaceRoom scoring.

        In RaceRoom, lap_time_previous_self belongs to the lap that just finished.
        During lap N+1 it normally contains the official time for lap N.
        Therefore we first look at exact next-lap samples and only then use
        conservative fallbacks. This keeps Sarthe times close to the sim/SimHub
        timing without needing SimHub.
        """
        if not rows or lap_number is None or lap_number < 0:
            return 0.0
        try:
            lap_number = int(lap_number)
        except Exception:
            return 0.0

        exact_next = [float(getattr(s, "last_lap_time", 0.0)) for s in rows if int(getattr(s, "lap_number", -999)) == lap_number + 1]
        val = self._stable_timing_value(exact_next)
        if val > 0:
            return val

        exact_completed_next = [float(getattr(s, "last_lap_time", 0.0)) for s in rows if int(getattr(s, "completed_laps", -999)) == lap_number + 1]
        val = self._stable_timing_value(exact_completed_next)
        if val > 0:
            return val

        # Fallback: sometimes the finished lap is stored in rows where the current
        # telemetry lap number already advanced inconsistently. Use a narrow window.
        narrow = [float(getattr(s, "last_lap_time", 0.0)) for s in rows if lap_number <= int(getattr(s, "lap_number", -999)) <= lap_number + 2]
        val = self._stable_timing_value(narrow)
        if val > 0:
            return val

        return 0.0

    def sim_official_lap_time_for_lap_from_rows(self, rows: List[Sample], lap_number: int) -> float:
        # Backwards-compatible wrapper: first true per-lap scoring, then no blind best-lap fallback.
        # Best-lap fallback made every lap look like the current best and confused reports/export.
        return self.sim_scoring_time_for_lap_from_rows(rows, lap_number)

    def sim_best_lap_from_scoring(self) -> float:
        vals = [float(getattr(s, "best_lap_time", 0.0)) for s in self.samples if 20.0 <= float(getattr(s, "best_lap_time", 0.0)) <= 1800.0]
        return min(vals) if vals else 0.0

    def timing_probe_report_lines(self) -> List[str]:
        lines = ["", "Scoring-Timing-Probe:"]
        if not self.samples:
            lines.append("Noch keine Samples vorhanden.")
            return lines
        best = self.sim_best_lap_from_scoring()
        if best > 0:
            lines.append(f"best_lap_time aus Scoring: {fmt_lap_time(best)} ({best:.3f} s)")
        else:
            lines.append("best_lap_time aus Scoring: nicht verfügbar")
        last_vals = [float(getattr(s, "last_lap_time", 0.0)) for s in self.samples if 20.0 <= float(getattr(s, "last_lap_time", 0.0)) <= 1800.0]
        if last_vals:
            lines.append(f"last_lap_time Werte erkannt: {len(last_vals)} Samples | min {fmt_lap_time(min(last_vals))} | max {fmt_lap_time(max(last_vals))}")
        else:
            lines.append("last_lap_time Werte erkannt: keine plausiblen Werte")
        lines.append("Per-Lap-Zuordnung: die offizielle Rundenzeit (lap_time_previous_self) wird auf der Folgerunde gelesen; SimHub ist dafür nicht nötig.")
        lines.append("Lap | Scoring-Zeit | Interne Zeit | Quelle")
        if not self.lap_summaries:
            self.update_laps()
        for l in self.lap_summaries[:30]:
            official = self.sim_scoring_time_for_lap_from_rows(self.samples, l.lap_number)
            if official > 0:
                lines.append(f"{l.lap_number} | {fmt_lap_time(official)} | {fmt_lap_time(l.duration_s)} | Scoring")
            else:
                lines.append(f"{l.lap_number} | - | {fmt_lap_time(l.duration_s)} | intern/Fallback")
        return lines

    def sim_official_lap_time_for_lap(self, lap_number: int) -> float:
        return self.sim_official_lap_time_for_lap_from_rows(self.samples, lap_number)

    def lap_time_for_report(self, lap: LapSummary) -> float:
        if not lap:
            return 0.0
        official = self.sim_official_lap_time_for_lap(lap.lap_number)
        if official > 0:
            return official
        return lap.duration_s

    def lap_time_for_export(self, lap: LapSummary) -> float:
        official = self.sim_official_lap_time_for_lap(lap.lap_number)
        if official > 0:
            return official
        est = self.estimated_lap_time_from_speed(lap.lap_number)
        if est < 999998.0 and est > 0:
            return est
        return lap.duration_s

    def estimated_lap_time_from_rows(self, rows: List[Sample], lap_number: int) -> float:
        official = self.sim_official_lap_time_for_lap_from_rows(rows, lap_number)
        if official > 0:
            return official
        segs = self.build_segment_summaries_from_rows(rows, lap_number)
        if not segs:
            return 999999.0
        return sum(s.seg_time_s for s in segs.values())

    def build_reference_payload_from_rows(self, lap: LapSummary, source_rows: List[Sample]) -> Optional[dict]:
        lap_samples = [s for s in source_rows if s.lap_number == lap.lap_number and not self.is_non_driving_sample(s)]
        if not lap_samples:
            return None
        first = lap_samples[0]
        vclass = infer_vehicle_class(first.vehicle_class, first.vehicle_name, first.vehicle_model)
        segs = self.build_segment_summaries_from_rows(lap_samples, lap.lap_number)
        if not segs:
            return None
        lap_time = self.estimated_lap_time_from_rows(lap_samples, lap.lap_number)
        meta = {
            "format": "pitboss_r3e_reference_v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "auto_export": True,
            "track": first.track,
            "vehicle_class": vclass,
            "vehicle_name": first.vehicle_name,
            "vehicle_model": first.vehicle_model,
            "lap_number": lap.lap_number,
            "lap_time_s": lap_time,
            "avg_speed": lap.avg_speed,
            "fuel_used_l": lap.fuel_used_l,
            "setup_label": self.selected_setup_label(),
            "driver_hardware_profile": self.selected_hardware_profile(),
        }
        return {
            "meta": meta,
            "segments": [self.segment_to_dict(x) for x in segs.values()],
            "path": [{"pos_x": x.pos_x, "pos_z": x.pos_z, "lap_dist_m": x.lap_dist_m, "speed_kmh": x.speed_kmh} for x in lap_samples],
        }

    def build_reference_payload_for_lap(self, lap: LapSummary) -> Optional[dict]:
        return self.build_reference_payload_from_rows(lap, self.samples)

    def best_exportable_lap(self) -> Optional[LapSummary]:
        clean = [l for l in self.lap_summaries if self.lap_eval_ok(l)]  # 0.2.31
        if not clean:
            return None
        max_cov = max((l.coverage_m for l in clean), default=0.0)
        candidates = []
        for l in clean:
            # Extra guard for auto-reference export: only full flying laps with enough data.
            if l.valid_samples < max(80, int(max(1.0, l.coverage_m) / 65.0)):
                continue
            if max_cov and l.coverage_m < max_cov * 0.93:
                continue
            if l.fuel_used_l > 0 and l.fuel_used_l < 0.75:
                continue
            ltime = self.lap_time_for_export(l)
            if ltime < 30 or l.avg_speed < 120:
                continue
            segs = self.build_segment_summaries_for_lap(l.lap_number)
            if len(segs) < 40:
                continue
            candidates.append(l)
        if not candidates:
            return None
        return min(candidates, key=lambda l: self.lap_time_for_export(l))

    def auto_bestlap_file_path(self, payload: dict, lap: LapSummary, lap_time: float) -> Path:
        meta = payload.get("meta", {})
        track = safe_filename_part(meta.get("track", "track"))
        vclass = safe_filename_part(meta.get("vehicle_class", "class"))
        car = safe_filename_part(meta.get("vehicle_model") or meta.get("vehicle_name") or "car")[:42]
        time_txt = fmt_lap_time(lap_time).replace(":", "-")
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return REFERENCE_DIR / f"reference_AUTO_{track}_{vclass}_{car}_{time_txt}_lap{lap.lap_number}_{stamp}.json"

    def activate_auto_reference_payload(self, payload: dict, path: Path, lap: LapSummary, lap_time: float, live: bool = False):
        self.auto_bestlap_export_path = str(path)
        self.auto_bestlap_lap_number = lap.lap_number
        self.auto_bestlap_time_s = lap_time
        self.external_reference = payload
        self.use_external_reference = True
        self.refresh_lap_combos()
        src = "Live-Bestlap" if live else "Auto-Bestlap"
        self.log.append(f"{src} exportiert und als Referenz aktiviert: Lap {lap.lap_number} | {fmt_lap_time(lap_time)} | {path}")
        self.refresh_dashboard()

    def auto_export_bestlap_reference(self):
        if not self.auto_bestlap_export_enabled:
            return
        lap = self.best_exportable_lap()
        if not lap:
            self.log.append("Auto-Bestlap-Export: keine geeignete saubere Runde gefunden.")
            return
        lap_time = self.lap_time_for_export(lap)
        payload = self.build_reference_payload_for_lap(lap)
        if not payload:
            self.log.append("Auto-Bestlap-Export: Referenzdaten konnten nicht erstellt werden; keine gültige komplette Runde im Live-Puffer.")
            return
        path = self.auto_bestlap_file_path(payload, lap, lap_time)
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.activate_auto_reference_payload(payload, path, lap, lap_time, live=False)
        except Exception as e:
            self.log.append(f"Auto-Bestlap-Export fehlgeschlagen: {e}")
        self.refresh_dashboard()

    def export_reference_lap(self):
        if not self.reference_lap:
            QMessageBox.warning(self, "Referenz exportieren", "Keine Referenzrunde vorhanden. Erst Recording stoppen und Referenz erzeugen.")
            return
        payload = self.build_reference_payload_for_lap(self.reference_lap)
        if not payload:
            QMessageBox.warning(self, "Referenz exportieren", "Keine vollständigen Referenzdaten für diese Runde gefunden.")
            return
        meta = payload.get("meta", {})
        lap_time = fnum(meta.get("lap_time_s"))
        default = REFERENCE_DIR / f"reference_{safe_filename_part(meta.get('track','track'))}_{safe_filename_part(meta.get('vehicle_class','class'))}_{fmt_lap_time(lap_time).replace(':','-')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Referenzrunde exportieren", str(default), "Referenz (*.json)")
        if not path:
            return
        # Manual exports are marked as normal reference files.
        payload.setdefault("meta", {})["auto_export"] = False
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log.append(f"Referenz exportiert: {path}")

    def import_reference_lap(self):
        path, _ = QFileDialog.getOpenFileName(self, "Referenzrunde importieren", str(REFERENCE_DIR), "Referenz (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.warning(self, "Referenz importieren", f"Datei konnte nicht gelesen werden:\n{e}")
            return
        meta = payload.get("meta", {})
        if meta.get("format") != "pitboss_r3e_reference_v1":
            QMessageBox.warning(self, "Referenz importieren", "Keine gültige PitBoss-R3E-Referenzdatei.")
            return
        cur_track, cur_class, cur_car = self.current_context()
        ref_track = meta.get("track", "")
        ref_class = meta.get("vehicle_class", "Unbekannt")
        warnings = []
        if cur_track and ref_track and cur_track != ref_track:
            warnings.append(f"Strecke anders: aktuell {cur_track} / Referenz {ref_track}")
        if cur_class and ref_class and cur_class != "Unbekannt" and ref_class != "Unbekannt" and cur_class != ref_class:
            warnings.append(f"Fahrzeugklasse anders: aktuell {cur_class} / Referenz {ref_class}")
        if warnings:
            msg = "Referenz passt möglicherweise nicht:\n" + "\n".join(warnings) + "\n\nTrotzdem laden?"
            if QMessageBox.question(self, "Referenz importieren", msg) != QMessageBox.Yes:
                return
        self.external_reference = payload
        self.use_external_reference = True
        self.log.append(f"Externe Referenz geladen und aktiviert: {self.external_reference_label()}")
        if cur_class == ref_class and cur_car and meta.get("vehicle_name") and cur_car != meta.get("vehicle_name"):
            self.log.append("Hinweis: gleiche Klasse, anderes Fahrzeug — Vergleich ist erlaubt, aber fahrzeugspezifische Unterschiede beachten.")
        self.refresh_lap_combos(); self.update_lap_compare(); self.update_heatmap(); self.update_coach_text(); self.refresh_dashboard()

    def open_export_folder(self):
        for _d in (EXPORT_DIR, REPORT_DIR, CSV_DIR, REFERENCE_DIR):
            _d.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(EXPORT_DIR)))

    def parse_ref(self, edit: QLineEdit) -> Optional[float]:
        txt = edit.text().strip().replace(",", ".")
        if not txt:
            return None
        try:
            return float(txt)
        except Exception:
            return None

    def refresh_lap_combos(self):
        if not hasattr(self, "ref_lap_combo"):
            return
        clean = [l for l in self.lap_summaries if self.lap_eval_ok(l)]  # 0.2.31
        old_ref = "__external__" if self.use_external_reference and self.external_reference else self.manual_reference_lap
        old_cmp = self.manual_compare_lap
        self.ref_lap_combo.blockSignals(True); self.cmp_lap_combo.blockSignals(True)
        self.ref_lap_combo.clear(); self.cmp_lap_combo.clear()
        self.ref_lap_combo.addItem("Auto – beste Sessionrunde", None)
        if self.external_reference:
            self.ref_lap_combo.addItem("Importierte Referenz AKTIV/auswählbar – " + self.external_reference_label(short=True), "__external__")
        self.cmp_lap_combo.addItem("Auto – beste Vergleichsrunde", None)
        for l in clean:
            t = self.estimated_lap_time_from_speed(l.lap_number)
            label = f"Lap {l.lap_number} | {fmt_lap_time(t)}* | Avg {l.avg_speed:.1f}"
            self.ref_lap_combo.addItem("Session: " + label, l.lap_number)
            self.cmp_lap_combo.addItem(label, l.lap_number)
        def select(combo, val):
            idx = 0
            if val is not None:
                for i in range(combo.count()):
                    if combo.itemData(i) == val:
                        idx = i; break
            combo.setCurrentIndex(idx)
        select(self.ref_lap_combo, old_ref); select(self.cmp_lap_combo, old_cmp)
        self.ref_lap_combo.blockSignals(False); self.cmp_lap_combo.blockSignals(False)

    def apply_lap_selection(self):
        ref_choice = self.ref_lap_combo.currentData()
        self.use_external_reference = (ref_choice == "__external__")
        self.manual_reference_lap = None if self.use_external_reference else ref_choice
        self.manual_compare_lap = self.cmp_lap_combo.currentData()
        if self.manual_reference_lap is not None and self.manual_compare_lap is not None and self.manual_reference_lap == self.manual_compare_lap:
            QMessageBox.warning(self, "Rundenauswahl", "Referenz und Vergleich dürfen nicht dieselbe Runde sein.")
            self.manual_compare_lap = None
            self.cmp_lap_combo.setCurrentIndex(0)
        self.update_laps()
        self.update_segments()
        self.update_lap_compare()
        self.update_heatmap()
        self.update_coach_text()
        ref_log = "Import" if self.use_external_reference else (self.manual_reference_lap or "Auto")
        self.log.append(f"Rundenauswahl angewendet: Referenz={ref_log} | Vergleich={self.manual_compare_lap or 'Auto'}")
        self.refresh_dashboard()

    def lap_by_number(self, lap_number: Optional[int]) -> Optional[LapSummary]:
        if lap_number is None:
            return None
        for l in self.lap_summaries:
            if l.lap_number == lap_number and self.lap_eval_ok(l):  # 0.2.31: manuelle Referenz erlaubt bei 'Ungültige Runden in Auswertung'
                return l
        return None

    def start_finish_warning(self) -> str:
        if not self.segment_deltas:
            return ""
        start_losses = [d for d in self.segment_deltas if d.start_m < 250 and d.delta_s > 0.10]
        if not start_losses:
            return ""
        loss = sum(d.delta_s for d in start_losses)
        spd = sum(d.speed_delta for d in start_losses) / max(1, len(start_losses))
        if loss >= 0.25 and spd < -15:
            return f"Hinweis: Start/Ziel-Bereich 0-250 m wirkt verfälscht oder stark ausgangsabhängig ({loss:+.3f} s, Speed {spd:+.1f} km/h). Für die Fahranalyse zuerst die nächste echte Brems-/Kurvenzone priorisieren."
        return ""

    def maybe_export_live_bestlap(self, rows: List[Sample], lap_number: Optional[int]):
        if not self.auto_bestlap_export_enabled or self.recording:
            return
        if not rows or lap_number is None or len(rows) < 80:
            return
        # Schwellen streckenlaengenabhaengig (RaceRoom: langsame Autos/kurze Strecken)
        track_m = max([r.lap_dist_m for r in rows if r.lap_dist_m >= 0] or [0.0])
        if track_m < 500.0:
            return
        summaries = self.build_lap_summaries_from_rows(rows)
        lap = None
        for l in summaries:
            if l.lap_number == lap_number:
                lap = l
                break
        if not lap or not lap.is_clean:
            return
        if lap.valid_samples < max(80, int(track_m / 50.0)) or lap.coverage_m < 0.85 * track_m or lap.avg_speed < 20:
            return
        segs = self.build_segment_summaries_from_rows(rows, lap.lap_number)
        if len(segs) < max(10, int(0.7 * track_m / 50.0)):
            return
        lap_time = sum(x.seg_time_s for x in segs.values())
        if self.auto_bestlap_time_s is not None and lap_time >= self.auto_bestlap_time_s - 0.001:
            return
        payload = self.build_reference_payload_from_rows(lap, rows)
        if not payload:
            return
        path = self.auto_bestlap_file_path(payload, lap, lap_time)
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.activate_auto_reference_payload(payload, path, lap, lap_time, live=True)
        except Exception as e:
            self.log.append(f"Live-Bestlap-Export fehlgeschlagen: {e}")

    def sample_vehicle_signature(self, s: Sample):
        """Stabiler Schlüssel für den Recording-Lock.
        Ziel: Ein Recording darf nicht versehentlich mehrere Fahrzeuge/Klassen mischen.
        """
        track = (s.track or "").strip()
        vclass = infer_vehicle_class(s.vehicle_class, s.vehicle_name, s.vehicle_model)
        name = (s.vehicle_model or s.vehicle_name or "").strip()
        if not track or not name:
            return None
        return (track, vclass, name)

    def sample_vehicle_label(self, sig) -> str:
        if not sig:
            return "nicht gesetzt"
        return f"{sig[0]} | {sig[1]} | {sig[2]}"

    def accept_recording_sample(self, s: Sample) -> bool:
        """Schützt Reports/CSV vor Fahrzeug- oder Klassenwechseln während einer Aufnahme.
        4.4.12: Der Lock wird erst auf ein wirklich fahrendes Auto gesetzt.
        Garage-/Stand-/Menü-Samples vor dem Losfahren werden verworfen, damit nicht versehentlich
        ein falsches Fahrzeug oder KI/Replay-Slot als Sessionbasis dient.
        """
        if not self.recording:
            return True
        sig = self.sample_vehicle_signature(s)
        if sig is None:
            self.rejected_sample_count += 1
            return False
        # Vor dem ersten echten Fahr-Sample noch nicht locken.
        if self.recording_signature is None and self.is_prelock_non_driving_sample(s):
            self.rejected_sample_count += 1
            if self.rejected_sample_count in (1, 10, 50) or self.rejected_sample_count % 250 == 0:
                self.log.append(f"Warte auf erstes Fahrsample für Recording-Lock ({self.rejected_sample_count} Stand-/Pit-Samples verworfen).")
            return False
        if self.recording_signature is None:
            self.recording_signature = sig
            self.log.append(f"Recording-Fahrzeug gelockt: {self.sample_vehicle_label(sig)}")
            return True
        if sig != self.recording_signature:
            # 0.5.9.24: Strecken-/Fahrzeugwechsel während der Aufnahme. Statt die Samples
            # nur endlos zu verwerfen: nach einer stabilen Serie desselben NEUEN Signaturs
            # (Debounce gegen einzelne verrauschte/kurz falsche Frames) die laufende Session
            # automatisch stoppen (Report/CSV/Referenz werden dabei wie gewohnt gespeichert)
            # und sofort neu starten, damit sich der neue Kontext frisch einlockt.
            if self.auto_switch_recording_enabled and not self.is_prelock_non_driving_sample(s):
                if self.pending_switch_signature == sig:
                    self.pending_switch_count += 1
                else:
                    self.pending_switch_signature = sig
                    self.pending_switch_count = 1
                if self.pending_switch_count >= AUTO_SWITCH_DEBOUNCE_SAMPLES:
                    old_label = self.sample_vehicle_label(self.recording_signature)
                    new_label = self.sample_vehicle_label(sig)
                    self.pending_switch_signature = None
                    self.pending_switch_count = 0
                    self.log.append(
                        f"Automatischer Wechsel erkannt: {new_label} statt {old_label} – "
                        "aktuelle Session wird gespeichert, neue Aufnahme startet automatisch."
                    )
                    self.stop_recording()
                    self.start_recording()
                    return False  # dieses Sample gehört zur alten Session, bereits geschlossen
            self.rejected_sample_count += 1
            if self.rejected_sample_count in (1, 5, 20) or self.rejected_sample_count % 100 == 0:
                self.log.append(
                    "Sample verworfen wegen Fahrzeug-/Klassenwechsel: "
                    f"{self.sample_vehicle_label(sig)} statt {self.sample_vehicle_label(self.recording_signature)} "
                    f"({self.rejected_sample_count} verworfen)"
                )
            return False
        # Kontinuierlich passendes Signal: Wechsel-Verdacht zurücksetzen.
        self.pending_switch_signature = None
        self.pending_switch_count = 0
        # Harte Stand-/Pit-Samples nach dem Lock dürfen nicht in Auswertungen/CSV dominieren.
        # Langsame Kurven werden NICHT verworfen, nur echte Pit/Garage/0-RPM/0-Speed-Zustände.
        if self.is_hard_garage_sample(s):
            self.rejected_sample_count += 1
            return False
        return True

    def update_live_smooth_lap_clock(self, s: Sample):
        """0.5.9.27 (Fix von 0.5.9.26): main.lap_time_current_self (current_lap_time) kommt aus
        dem RaceRoom-Scoring-Block, der in groesseren Schritten aktualisiert als die
        Telemetrie -> im Rundenzeiten-Overlay "AKTUELL" blieb der Wert zwischendurch
        kurz stehen statt smooth mitzulaufen, obwohl wir selbst mit vollen 10 Hz pollen.
        0.5.9.26 hatte dafuer eine eigene Echtzeit-Uhr per time.monotonic() gebaut, die
        sich resynct, sobald der Sim-Rohwert um mehr als 0.35s von unserer eigenen
        Hochrechnung abweicht.
        BUGFIX 0.5.9.27: genau dieser Resync war die Ursache fuer Marcels ~4s-zu-
        kleine Anzeige. Der Sim-Rohwert aktualisiert offenbar nur alle paar Sekunden
        und ist DANN noch der Stand von vor der Aktualisierungsluecke (kein neuer,
        aktueller Wert, sondern ein "frisch eingetroffener alter" Wert) -> unsere
        eigene, bereits weiter fortgeschrittene Uhr wurde bei jedem Sim-Update auf
        diesen niedrigeren Stand zurueckgeworfen und driftete dadurch systematisch
        nach unten. Echte Rundenzeit kann innerhalb derselben Runde nie zurueck-
        springen -> Resync jetzt NUR noch vorwaerts: der Rohwert darf unsere Uhr
        NACHZIEHEN (falls wir mal zu langsam liefen), aber niemals zurueckdrehen.
        Rueckwaerts-Reset ausschliesslich bei echtem Rundenwechsel/Reset/Erststart.
        """
        try:
            raw = float(getattr(s, "current_lap_time", 0.0) or 0.0)
            lap = int(getattr(s, "lap_number", 0) or 0)
        except Exception:
            self.live_smooth_lap_time = None
            return
        now = time.monotonic()
        anchor_raw = self._live_clock_anchor_raw
        anchor_ts = self._live_clock_anchor_ts
        hard_reset = (
            raw <= 0.0
            or lap != self._live_clock_lap
            or anchor_raw is None
            or anchor_ts is None
        )
        if hard_reset:
            self._live_clock_anchor_raw = raw
            self._live_clock_anchor_ts = now
            self._live_clock_lap = lap
            self.live_smooth_lap_time = raw
            return
        predicted = anchor_raw + (now - anchor_ts)
        if raw > predicted + 0.02:
            # Sim-Rohwert hat unsere Hochrechnung eingeholt/ueberholt -> nach VORNE
            # nachziehen (z.B. nach kurzem Frame-Haenger). Niemals rueckwaerts.
            self._live_clock_anchor_raw = raw
            self._live_clock_anchor_ts = now
            self.live_smooth_lap_time = raw
        else:
            self.live_smooth_lap_time = predicted

    def live_tick(self):
        """Live-Abfrage für Overlay, unabhängig vom Recording.
        Liest RaceRoom_Data, schreibt aber keine Export-/Recording-Samples.
        Dadurch funktionieren Speed/Gang/Live-Delta auch ohne Recording.
        """
        try:
            s = self.reader.read_sample()
        except Exception as e:
            # 0.2.0: Backoff. Laeuft RaceRoom nicht, reicht 1 Hz statt 10 Hz.
            self._live_fail = getattr(self, "_live_fail", 0) + 1
            # 0.2.39: Verbindungsdiagnose. Der Fehlergrund (z. B. "Shared Memory
            # nicht gefunden" oder "keine aktiven Fahrzeuge") wird sichtbar:
            # bei jedem neuen Grund sofort, danach hoechstens alle 60 s im Log;
            # die Kachel "Verbindung", die Statusleiste und der Stopp-Dialog
            # zeigen ihn ebenfalls (self._live_err).
            _err = str(e)
            _now = time.monotonic()
            if _err != getattr(self, "_live_err", None):
                self._live_err = _err
                self._live_err_ts = _now
                self.log.append(f"RaceRoom-Verbindung FEHLER: {_err}")
            elif _now - getattr(self, "_live_err_ts", 0.0) >= 60.0:
                self._live_err_ts = _now
                self.log.append(f"RaceRoom-Verbindung weiterhin FEHLER: {_err}")
            if self._live_fail >= 5 and self.live_timer.interval() != 1000:
                self.live_timer.setInterval(1000)
            return
        if getattr(self, "_live_fail", 0) or self.live_timer.interval() != 100:
            self._live_fail = 0
            self.live_timer.setInterval(100)
        if getattr(self, "_live_err", None):
            self.log.append(f"RaceRoom-Verbindung OK (zuvor: {self._live_err})")
            self._live_err = None
            self._live_err_ts = 0.0
        self._last_read_ok_ts = time.monotonic()
        self.last_live_sample = s
        try:
            set_tire_temp_window(s.tire_temp_cold_c, s.tire_temp_opt_c, s.tire_temp_hot_c)
        except Exception:
            pass
        self.update_live_smooth_lap_clock(s)  # 0.5.9.26
        self.write_live_log_row(s)  # 0.5.9.26
        self.maybe_autoshow_tire_overlay(s)
        self.update_live_lap_buffer(s)
        self.update_corner_name_overlay()  # 0.2.37: Kurven-Namen-Overlay live aktualisieren
        # 0.2.0: Live-Delta baut Segmente aus der laufenden Runde - ca. 3 Hz reichen voellig.
        self._delta_tick = getattr(self, "_delta_tick", 0) + 1
        if self._delta_tick % 3 == 0:
            self.compute_live_reference_delta()
        # 0.5.9.15/17: CPU/GPU-Entlastung. Bis zu 13 Overlay-Fenster sind einzeln
        # WA_TranslucentBackground + WindowStaysOnTopHint -> jedes .update() hier
        # zwingt Windows/DWM, alle sichtbaren davon neu zu kompositieren. Waehrend
        # aktiv gefahren wird bleibt das bei vollen 10 Hz (kein Verhaltensunterschied
        # im Cockpit/auf der Strecke). Steht das Auto (Menue/Stand/Box, auch mit
        # laufendem Motor) aendern sich die angezeigten Werte kaum -> dort reicht
        # 2 Hz, das reduziert die DWM-Kompositierlast dort um 80% und entlastet
        # spuerbar auch das eigene Menue. Rein additiv: refresh_overlay()/
        # paintEvent-Logik unveraendert.
        self._overlay_tick_n = getattr(self, "_overlay_tick_n", 0) + 1
        try:
            # 0.5.9.17: eigene, lockere Erkennung nur fuers Overlay-Throttling statt
            # is_hard_garage_sample (die ist fuer die Rundenanalyse gedacht und verlangt
            # zusaetzlich RPM<500 -> in Box/Garage mit laufendem Motor (Standgas oft
            # 800-1200 RPM) griff die Drosselung deshalb NICHT, PitBoss blieb dort bei
            # vollen 10 Hz. Hier zaehlt nur: bewegt sich das Auto ueberhaupt.
            _driving = not (bool(getattr(s, "in_pits", False))
                             or float(getattr(s, "speed_kmh", 0.0) or 0.0) < 2.0)
        except Exception:
            _driving = True
        _do_refresh = _driving
        if not _driving and self._overlay_tick_n % 5 == 0:
            # 0.5.9.18: Dirty-Check. Bisher wurde im Stand/Box trotz Drosselung noch
            # JEDE 5. Tick (2 Hz) blind neu gezeichnet, auch wenn sich an der Telemetrie
            # ueberhaupt nichts geaendert hat (Marcel: "durchgehend etwas ruckelig, kein
            # klares Muster"). Fingerprint = alle Sample-Felder AUSSER timestamp (der
            # aendert sich immer und wuerde die Erkennung sonst nutzlos machen). Nur bei
            # tatsaechlicher Aenderung neu zeichnen. Zwangs-Refresh alle 5s als Netz fuer
            # Anzeigen, die NICHT direkt am Sample haengen (Wetter-Trend-Modell, REST-
            # Verschleiss/Setup alle 12s im Hintergrund-Thread, Schadenmodell) -> die
            # koennen sich aendern, ohne dass sich das Sample selbst aendert.
            try:
                fp = _dc_astuple(s)[1:] if s is not None else None
            except Exception:
                fp = None
            self._idle_refresh_n = getattr(self, "_idle_refresh_n", 0) + 1
            changed = fp != getattr(self, "_last_overlay_fp", "unset")
            forced = (self._idle_refresh_n % 10 == 0)  # 10 x 500ms = alle 5s
            if changed or forced or fp is None:
                self._last_overlay_fp = fp
                _do_refresh = True
        if _do_refresh:
            self.refresh_overlay()
        self.live_coach.maybe_speak_on_straight(s)
        self.brake_coach.update(s)
        self.update_sector_times(s)  # 0.4.9.0
        self.maybe_autoshow_pit_overlay(s)  # 0.4.9.1
        self.maybe_autoshow_flag_overlay(s)  # 0.5.5.0
        self.brake_model.update(s)  # 0.4.9.2
        self.damage_model.update(s)  # 0.4.9.4
        self.update_brake_status()  # 0.4.9.4

    def update_live_lap_buffer(self, s: Sample):
        if self.is_non_driving_sample(s) or s.lap_dist_m < 0 or s.speed_kmh < 1:
            return
        reset = False
        if self.live_lap_number is None or self.live_lap_number != s.lap_number:
            reset = True
        elif self.live_lap_samples and s.lap_dist_m < self.live_lap_samples[-1].lap_dist_m - 500:
            reset = True
        if reset:
            if self.live_lap_samples:
                completed = list(self.live_lap_samples)
                self.consider_live_completed_lap_as_reference(completed, self.live_lap_number)
                self.maybe_export_live_bestlap(completed, self.live_lap_number)
                self.refresh_corner_list(completed)  # 0.2.37: Kurven der Strecke erkennen
                self.live_coach.on_lap_completed(completed, self.live_lap_number,
                                                 self.live_delta_s, self.live_coach_line)
                try:
                    self.update_laps()  # 0.2.11: Live-Rundenliste direkt nach Rundenwechsel aktualisieren
                except Exception:
                    pass
            self.live_lap_number = s.lap_number
            self.live_lap_samples = []
            self.live_delta_s = None
            self.live_coach_line = "Live sammelt Daten"
        self.live_lap_samples.append(s)
        if len(self.live_lap_samples) > 2000:  # 0.4.8.5: reicht auch fuer lange Runden (>90s)
            self.live_lap_samples = self.live_lap_samples[-2000:]

    def consider_live_completed_lap_as_reference(self, rows: List[Sample], lap_number: Optional[int]):
        """Während Recording/Live: abgeschlossene saubere Runde als temporäre Live-Referenz nutzen.
        Dadurch zeigt das Minimal-Overlay Delta/Coach schon während der nächsten Runde, ohne Stop.
        """
        if not rows or lap_number is None or len(rows) < 80:
            return
        # Schwellen streckenlaengenabhaengig (RaceRoom: langsame Autos/kurze Strecken)
        track_m = max([r.lap_dist_m for r in rows if r.lap_dist_m >= 0] or [0.0])
        if track_m < 500.0:
            return
        try:
            summaries = self.build_lap_summaries_from_rows(rows)
            lap = next((l for l in summaries if l.lap_number == lap_number), None)
            if not lap or not lap.is_clean:
                return
            if lap.valid_samples < max(80, int(track_m / 50.0)) or lap.coverage_m < 0.85 * track_m or lap.avg_speed < 20:
                return
            segs = self.build_segment_summaries_from_rows(rows, lap_number)
            if len(segs) < max(10, int(0.7 * track_m / 50.0)):
                return
            lap_time = sum(x.seg_time_s for x in segs.values())
            if not math.isfinite(lap_time) or lap_time <= 10:
                return
            if self.live_best_reference_time_s is None or lap_time < self.live_best_reference_time_s - 0.001:
                self.live_best_reference_segments = segs
                self.live_best_reference_lap = lap_number
                self.live_best_reference_time_s = lap_time
                self.live_coach_line = f"Live-Ref Lap {lap_number}"
                self.brake_coach.set_reference_from_rows(rows)
        except Exception as e:
            try:
                self.log.append(f"Live-Referenz übersprungen: {e}")
            except Exception:
                pass

    def live_reference_segments(self) -> dict:
        # 0.2.0: Ergebnis cachen. Die Referenzrunde aendert sich waehrend der Fahrt nicht;
        # der Schluessel deckt Referenzwechsel, neue Analyse und Loeschen ab.
        if self.external_reference is not None and self.use_external_reference:
            key = ("ext", id(self.external_reference))
        elif self.reference_lap:
            key = ("lap", self.reference_lap.lap_number, id(self.reference_lap), len(self.lap_summaries),
                   self.samples[0].timestamp if self.samples else None)
        else:
            key = None
        if key is not None:
            cached = getattr(self, "_ref_seg_cache", None)
            if cached is not None and cached[0] == key:
                return cached[1]
            if key[0] == "ext":
                segs = self.external_reference_segments()
            else:
                segs = self.build_segment_summaries_for_lap(self.reference_lap.lap_number)
            self._ref_seg_cache = (key, segs)
            return segs
        if getattr(self, "live_best_reference_segments", None):
            return self.live_best_reference_segments
        return {}

    def compute_live_reference_delta(self):
        if not self.live_lap_samples:
            self.live_delta_s = None
            self.live_coach_line = "Live sammelt Daten"
            return
        ref_segments = self.live_reference_segments()
        if not ref_segments:
            self.live_delta_s = None
            self.live_coach_line = "Referenz importieren/Analyse"
            return
        cmp_segments = self.build_segment_summaries_from_rows(self.live_lap_samples, self.live_lap_number or -1)
        if not cmp_segments:
            self.live_delta_s = None
            self.live_coach_line = "Live sammelt Daten"
            return
        current_m = self.live_lap_samples[-1].lap_dist_m
        current_key = int(current_m // 50) * 50
        keys = sorted(k for k in (set(ref_segments) & set(cmp_segments)) if k < current_key)
        if len(keys) < 3:
            self.live_delta_s = None
            self.live_coach_line = "Live sammelt Daten"
            return
        deltas = []
        for key in keys:
            d = cmp_segments[key].seg_time_s - ref_segments[key].seg_time_s
            if abs(d) < 2.0:  # Live-Schutz gegen stehendes Auto/Reset-Ausreißer
                deltas.append((key, d, cmp_segments[key], ref_segments[key]))
        if not deltas:
            self.live_delta_s = None
            self.live_coach_line = "Live sammelt Daten"
            return
        self.live_delta_s = sum(d for _, d, _, _ in deltas)
        losses = [(k, d, c, r) for k, d, c, r in deltas if d > 0.08]
        if losses:
            k, d, c, r = max(losses, key=lambda x: x[1])
            speed_diff = c.avg_speed - r.avg_speed
            if c.avg_throttle < r.avg_throttle - 0.12:
                topic = "Gas früher"
            elif speed_diff < -5:
                topic = "mehr Mindesttempo"
            elif c.max_brake > r.max_brake + 0.08:
                topic = "Bremse lösen"
            else:
                topic = "Linie ruhiger"
            self.live_coach_line = f"{k}-{k+50} m {d:+.2f}s · {topic}"
        else:
            self.live_coach_line = "aktuell ok"

    def capture_tick(self):
        self.snapshot(silent=True)

    def snapshot(self, silent: bool = False):
        try:
            s = self.reader.read_sample()
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "RaceRoom Shared Memory", f"Konnte RaceRoom-Daten ($R3E) nicht lesen:\n{e}\n\nLäuft RaceRoom und bist du in einer Session?")
            self.status.setText("RaceRoom-Daten ($R3E) nicht lesbar.")
            return
        if not self.accept_recording_sample(s):
            if not silent:
                self.log.append("Snapshot verworfen: anderes Fahrzeug/andere Klasse als Recording-Lock.")
            self.status.setText(f"Sample verworfen – Recording gelockt auf {self.sample_vehicle_label(self.recording_signature)}")
            return
        self.samples.append(s)
        # 0.2.4: Eingefrorene Telemetrie erkennen (Spiel beendet/Session verlassen):
        # RaceRoom liefert dann unveränderte Rohwerte weiter. Nach ~5 s identischen
        # Werten wird das Recording automatisch gestoppt, statt endlos Leerlauf zu sammeln.
        _frozen_key = (round(s.pos_x, 3), round(s.pos_z, 3), round(s.speed_kmh, 2), round(s.steering, 4), s.lap_dist_m)
        if _frozen_key == getattr(self, "_frozen_last_key", None):
            self._frozen_count = getattr(self, "_frozen_count", 0) + 1
        else:
            self._frozen_count = 0
            self._frozen_logged = False
        self._frozen_last_key = _frozen_key
        if self._frozen_count >= 45 and not getattr(self, "_frozen_logged", False):
            self._frozen_logged = True
            self.log.append("⚠️ Telemetrie eingefroren: identische Rohwerte über ~5 s (Spiel beendet/Session verlassen). Recording wird gestoppt.")
            if self.recording:
                self.stop_recording()
        if not silent:
            self.add_sample_to_table(s)
            self.trackmap.set_samples(self.samples)
            self.trackmap.set_sector_info(self.official_sector_bounds())  # 0.2.9
            self.status.setText(f"Letzter Snapshot: {s.track} | {s.vehicle_name} | {s.speed_kmh:.1f} km/h | Gear {s.gear} | Fuel {s.fuel_l:.2f} L")
            self.refresh_dashboard()
        if not silent:
            self.log.append(self.sample_summary(s))
            self.compare_refs(s)

    def start_recording(self):
        if self.recording:
            self.log.append("Recording läuft bereits – Start ignoriert.")
            return
        self.samples.clear(); self.lap_summaries.clear(); self.reference_lap = None; self.compare_lap = None; self.segment_deltas = []; self.manual_reference_lap = None; self.manual_compare_lap = None; self.auto_bestlap_export_path = None; self.auto_bestlap_lap_number = None; self.auto_bestlap_time_s = None; self.live_best_reference_segments = {}; self.live_best_reference_lap = None; self.live_best_reference_time_s = None; self.recording_signature = None; self.rejected_sample_count = 0; self.pending_switch_signature = None; self.pending_switch_count = 0; self.live_summary.setRowCount(0); self.segment_table.setRowCount(0); self.zone_table.setRowCount(0); self.laps_table.setRowCount(0); self.lap_overview_table.setRowCount(0); self.live_lap_table.setRowCount(0) if hasattr(self, "live_lap_table") else None; self.compare_table.setRowCount(0); self.coach_text.clear(); self.limit_coach_text.clear() if hasattr(self, "limit_coach_text") else None;
        self.input_table.setRowCount(0) if hasattr(self, "input_table") else None; self.input_coach_text.clear() if hasattr(self, "input_coach_text") else None; self.trackmap.set_samples([]);
        self.heatmap.set_samples([]) if hasattr(self, 'heatmap') else None; self.refresh_lap_combos()
        self.recording = True; self.timer.start()
        self.snapshot(silent=True)  # 0.4.8.1: Snapshot automatisch bei Start
        self._set_rec_ui(True)
        self.log.append("🔴 Recording gestartet: Auto-Report/CSV werden beim Stop automatisch gespeichert.")
        self.status.setText("🔴 RECORDING AKTIV – " + self.hotkey_config.get("record", "F8") + " stoppt und speichert Report/CSV automatisch.")
        self.refresh_dashboard()

    def _set_telemetry_cursor(self, dist):
        """0.2.27: Positions-Cursor (Rundenmeter) fuer Spuren + Input-Karte setzen.
        None = automatisch dem letzten Sample folgen."""
        self._telemetry_cursor_dist = dist
        if hasattr(self, "telemetry_trace"):
            self.telemetry_trace.set_cursor_dist(dist)
        if hasattr(self, "telemetry_map"):
            self.telemetry_map.set_cursor_dist(dist)

    def update_telemetry_view(self):
        """0.2.25: Telemetrie-Reiter - gewaehlte Runde, Kanal-Spuren + Input-Karte."""
        if not hasattr(self, "telemetry_trace"):
            return
        driven = [s for s in (self.samples or []) if float(getattr(s, "lap_dist_m", -1.0) or 0.0) >= 0 and float(s.speed_kmh) > 2.0]
        # Runden-Auswahl oben rechts: Liste nur bei Aenderung neu fuellen, Auswahl bewahren
        laps = sorted({int(s.lap_number) for s in driven if int(s.lap_number) > 0})
        if hasattr(self, "telemetry_lap_combo"):
            labels = ["Alle Runden"] + ["Runde " + str(n) for n in laps]
            cur_labels = [self.telemetry_lap_combo.itemText(i) for i in range(self.telemetry_lap_combo.count())]
            if cur_labels != labels:
                cur = self.telemetry_lap_combo.currentText()
                self.telemetry_lap_combo.blockSignals(True)
                self.telemetry_lap_combo.clear()
                self.telemetry_lap_combo.addItems(labels)
                idx = self.telemetry_lap_combo.findText(cur)
                self.telemetry_lap_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self.telemetry_lap_combo.blockSignals(False)
        rows = driven[-4000:]
        sel = self.telemetry_lap_combo.currentText() if hasattr(self, "telemetry_lap_combo") else "Alle Runden"
        if sel != "Alle Runden":  # 0.2.25: nur die gewaehlte Runde zeigen
            try:
                lapno = int(sel.replace("Runde ", ""))
                rows = [s for s in driven if int(s.lap_number) == lapno]
            except Exception:
                pass
        self.telemetry_trace.set_rows(rows)
        if hasattr(self, "telemetry_map"):
            self.telemetry_map.set_outline(driven)  # 0.2.26: Strecken-Umriss aus allen Runden
            self.telemetry_map.set_rows(rows)
        # 0.2.27: manuellen Cursor beibehalten (None = automatisch folgen)
        cur = getattr(self, "_telemetry_cursor_dist", None)
        self.telemetry_trace.set_cursor_dist(cur)
        if hasattr(self, "telemetry_map"):
            self.telemetry_map.set_cursor_dist(cur)
        if rows:
            tmax = 0.0
            bmax = 0.0
            for s in rows:
                if float(s.throttle) > tmax:
                    tmax = float(s.throttle)
                if float(s.brake) > bmax:
                    bmax = float(s.brake)
            self.telemetry_note.setText(sel + " | max Gas " + f"{tmax * 100:.0f}" + "% | max Bremse " + f"{bmax * 100:.0f}" + "% | Samples: " + str(len(rows)))
        else:
            self.telemetry_note.setText("Noch keine gefahrenen Samples.")

    def stop_recording(self):
        if not self.recording:
            self.log.append("Recording ist nicht aktiv – Stop ignoriert.")
            return
        self.recording = False; self.timer.stop()
        self._set_rec_ui(False)
        self.log.append(f"Recording gestoppt. Samples: {len(self.samples)} | verworfen wegen Fahrzeugwechsel/ungültig: {self.rejected_sample_count}")
        self.update_laps()
        self.auto_export_bestlap_reference()
        ref_samples = self.samples_for_reference_lap()
        self.trackmap.set_samples(ref_samples if ref_samples else self.samples)
        self.trackmap.set_sector_info(self.official_sector_bounds())  # 0.2.9
        self.update_segments()
        self.update_lap_compare()
        self.update_heatmap()
        self.update_telemetry_view()  # 0.2.21
        self.update_coach_text()
        self.update_input_coach()
        res_save = self.autosave_exports()  # 0.2.30: Ergebnis wird gleich ausgewertet
        self.autosave_feedback(res_save)
        self.refresh_dashboard()

    def clear(self):
        self.samples.clear(); self.lap_summaries.clear(); self.reference_lap = None; self.compare_lap = None; self.segment_deltas = []; self.manual_reference_lap = None; self.manual_compare_lap = None; self.auto_bestlap_export_path = None; self.auto_bestlap_lap_number = None; self.auto_bestlap_time_s = None; self.live_best_reference_segments = {}; self.live_best_reference_lap = None; self.live_best_reference_time_s = None; self.live_summary.setRowCount(0); self.segment_table.setRowCount(0); self.zone_table.setRowCount(0); self.laps_table.setRowCount(0); self.lap_overview_table.setRowCount(0); self.live_lap_table.setRowCount(0) if hasattr(self, "live_lap_table") else None; self.compare_table.setRowCount(0); self.coach_text.clear(); self.limit_coach_text.clear() if hasattr(self, "limit_coach_text") else None;
        self.input_table.setRowCount(0) if hasattr(self, "input_table") else None; self.input_coach_text.clear() if hasattr(self, "input_coach_text") else None; self.trackmap.set_samples([]);
        self.heatmap.set_samples([]) if hasattr(self, 'heatmap') else None; self.refresh_lap_combos(); self.log.clear()
        self.status.setText("Gelöscht.")
        self.refresh_dashboard()

    def sample_summary(self, s: Sample) -> str:
        return (
            f"Snapshot: Track={s.track} | Player={s.player_name} | idx={s.player_idx}/{s.active_vehicles} | "
            f"Car={s.vehicle_name} | speed={s.speed_kmh:.2f} km/h | gear={s.gear} | rpm={s.rpm:.0f} | "
            f"fuel={s.fuel_l:.3f} L | thr={s.throttle:.3f} | brake={s.brake:.3f} | steer={s.steering:.5f} | "
            f"lap={s.lap_number} dist={s.lap_dist_m:.1f} m | pos=({s.pos_x:.1f},{s.pos_z:.1f})"
        )

    def compare_refs(self, s: Sample):
        # 0.2.0: SimHub-Vergleichsfelder sind unsichtbar; Vergleich nur, wenn jemand sie per Code fuellt.
        parts = []
        for name, edit, val, unit in (("Speed", self.ref_speed, s.speed_kmh, "km/h"), ("Gear", self.ref_gear, float(s.gear), ""),
                                      ("Fuel", self.ref_fuel, s.fuel_l, "L"), ("Track m", self.ref_trackm, s.lap_dist_m, "m")):
            ref = self.parse_ref(edit)
            if ref is not None:
                parts.append(f"{name}: RaceRoom {val:.3f}{unit} / SimHub {ref:.3f}{unit} / Diff {val-ref:+.3f}")
        if parts:
            self.log.append("Vergleich: " + " | ".join(parts))

    def tire_rows_for_sample(self, s: Sample):
        return [
            ("VL", s.tire_fl_pressure_kpa, s.tire_fl_temp_l_c, s.tire_fl_temp_c_c, s.tire_fl_temp_r_c, s.tire_fl_carcass_c, s.tire_fl_wear_pct, s.tire_fl_flat, s.tire_fl_grip_fract),
            ("VR", s.tire_fr_pressure_kpa, s.tire_fr_temp_l_c, s.tire_fr_temp_c_c, s.tire_fr_temp_r_c, s.tire_fr_carcass_c, s.tire_fr_wear_pct, s.tire_fr_flat, s.tire_fr_grip_fract),
            ("HL", s.tire_rl_pressure_kpa, s.tire_rl_temp_l_c, s.tire_rl_temp_c_c, s.tire_rl_temp_r_c, s.tire_rl_carcass_c, s.tire_rl_wear_pct, s.tire_rl_flat, s.tire_rl_grip_fract),
            ("HR", s.tire_rr_pressure_kpa, s.tire_rr_temp_l_c, s.tire_rr_temp_c_c, s.tire_rr_temp_r_c, s.tire_rr_carcass_c, s.tire_rr_wear_pct, s.tire_rr_flat, s.tire_rr_grip_fract),
        ]

    def telemetry_channels_active(self) -> dict:
        """0.2.4: Erkennt Telemetrie-Kanäle, die das Spiel nicht liefert (im Spiel deaktiviert).

        RaceRoom füllt deaktivierte Kanäle mit konstanten Ruhe-Werten:
        Wear/Rest 100 %, Carcass 0,0 °C, Verbrauch 0,000 l.
        Ein Kanal gilt als aktiv, wenn er im Stint mindestens einmal vom
        Ruhe-Wert abgewichen ist. Ohne Samples neutral (True) zurückgeben,
        damit keine Entscheidung erzwungen wird.
        """
        if not self.samples:
            return {"wear": True, "carcass": True, "fuel": True}
        prefixes = ("tire_fl", "tire_fr", "tire_rl", "tire_rr")
        wear_vals = [float(getattr(s, f"{p}_wear_pct", 100.0) or 0.0) for s in self.samples for p in prefixes]
        wear_active = any(math.isfinite(v) and v < 99.5 for v in wear_vals)
        carc_vals = [float(getattr(s, f"{p}_carcass_c", 0.0) or 0.0) for s in self.samples for p in prefixes]
        carcass_active = any(math.isfinite(v) and v > 0.5 for v in carc_vals)
        fuel_vals = [float(getattr(s, "fuel_l", 0.0) or 0.0) for s in self.samples]
        fuel_active = bool(fuel_vals) and (max(fuel_vals) - min(fuel_vals)) > 0.05
        return {"wear": wear_active, "carcass": carcass_active, "fuel": fuel_active}

    def flatspot_status(self, flat: bool, grip_fract: float, brake: float = 0.0, speed_kmh: float = 0.0, sample: Optional[Sample] = None) -> str:
        # Echte RaceRoom-tire_flatspot-Meldung hat Vorrang, aber nur bei plausibler Fahrt.
        if flat and speed_kmh > 10:
            return "REIFEN PLATT"
        gf = max(0.0, float(grip_fract or 0.0))
        if brake <= 0.20 or speed_kmh <= 25:
            return "OK"
        is_abs_car = bool(getattr(sample, "abs_on", False)) if sample else False
        # ABS an: Sliding unter Bremse = ABS-Stress. ABS aus/nicht vorhanden: Sliding unter Bremse = Lockup-Risiko.
        # 0.2.4: Schwellen gelockert (ABS! ab 0.60 statt 0.45, ABS ab 0.35 statt 0.22) -
        # Nürburgring-Daten: schnellste Runde war die aggressivste, alte Schwellen warfen zu schnell "ABS!".
        if is_abs_car:
            if gf >= 0.60:
                return "ABS!"
            if gf >= 0.35:
                return "ABS"
            return "OK"
        if gf >= 0.35:
            return "LOCK!"
        if gf >= 0.18:
            return "LOCK"
        if gf >= 0.08:
            return "leicht"
        return "OK"

    def update_tire_table(self, s: Sample):
        if not hasattr(self, "tire_table"):
            return
        rows = self.tire_rows_for_sample(s)
        if self.tire_table.rowCount() != len(rows):
            self.tire_table.setRowCount(len(rows))
        notes = []
        # 0.2.4: Im Spiel deaktivierte Kanäle als solche anzeigen statt Ruhe-Werte als Messwerte.
        ch = self.telemetry_channels_active()
        for r, (name, pressure, tl, tc, tr, carcass, wear, flat, grip_fract) in enumerate(rows):
            avg_temp = (tl + tc + tr) / 3.0 if (tl or tc or tr) else 0.0
            spread = tr - tl
            flat_status = self.flatspot_status(flat, grip_fract, s.brake, s.speed_kmh, s)
            hint = self.tire_setup_hint(tl, tc, tr, pressure, wear)
            if hint and hint != "ok":
                notes.append(f"{name}: {hint}")
            vals = [
                name,
                f"{pressure:.1f}",
                f"{pressure/100.0:.2f}" if pressure > 0 else "-",
                f"{tl:.1f} °C",
                f"{tc:.1f} °C",
                f"{tr:.1f} °C",
                f"{carcass:.1f} °C" if ch["carcass"] else "— (Spiel aus)",
                f"{wear:.1f}" if ch["wear"] else "— (Spiel aus)",
                flat_status,
                hint if ch["wear"] else (hint + " | Wear: im Spiel deaktiviert" if hint else "Wear: im Spiel deaktiviert"),
            ]
            for c, v in enumerate(vals):
                it = self.tire_table.item(r, c)
                if it is None:
                    self.tire_table.setItem(r, c, QTableWidgetItem(str(v)))
                elif it.text() != str(v):
                    it.setText(str(v))
        _now = time.monotonic()
        if _now - getattr(self, "_tire_resize_ts", 0.0) > 5.0:
            self._tire_resize_ts = _now
            self.tire_table.resizeColumnsToContents()
        if hasattr(self, "tire_note"):
            note_txt = " | ".join(notes[:4]) if notes else "Reifen im aktuellen Snapshot unauffällig. Für echte Analyse 3–5 Runden Stintdaten sammeln."
            self.tire_note.setText(note_txt + " Flat/ABS-Anzeige: der echte Flatspot-Status hat Vorrang; bei aktivem ABS wird Sliding unter Bremse als ABS-Stress gewertet, ohne ABS als Lockup-Risiko.")

    def _fill_live_summary(self, s: Sample):
        vals = [
            s.lap_number, f"{s.lap_dist_m:.1f} m", f"{s.speed_kmh:.1f} km/h", s.gear,
            f"{s.fuel_l:.2f} L", fmt_lap_time(s.last_lap_time), fmt_lap_time(s.best_lap_time),
            "invalid" if s.lap_invalidated else ("Pit" if s.in_pits else "ok")
        ]
        if self.live_summary.rowCount() != 1:
            self.live_summary.setRowCount(1)
        for c, v in enumerate(vals):
            it = self.live_summary.item(0, c)
            if it is None:
                self.live_summary.setItem(0, c, QTableWidgetItem(str(v)))
            elif it.text() != str(v):
                it.setText(str(v))
        if self.live_summary.columnWidth(0) < 60:
            self.live_summary.resizeColumnsToContents()

    def add_sample_to_table(self, s: Sample):
        self._fill_live_summary(s)
        self.update_tire_table(s)

    def samples_for_reference_lap(self) -> List[Sample]:
        if not self.reference_lap:
            return []
        return [s for s in self.samples if s.lap_number == self.reference_lap.lap_number and not self.is_non_driving_sample(s)]

    def is_hard_garage_sample(self, s: Sample) -> bool:
        return bool(s.in_pits) or (s.speed_kmh < 1.0 and s.rpm < 500 and s.gear == 0)

    def is_prelock_non_driving_sample(self, s: Sample) -> bool:
        # Für den Fahrzeug-Lock warten wir auf ein plausibles Fahrsample.
        # Dadurch lockt die Aufnahme nicht auf Stand-/Boxen-/Menü-Daten.
        return self.is_hard_garage_sample(s) or s.lap_dist_m < -20 or s.speed_kmh < 5.0

    def is_non_driving_sample(self, s: Sample) -> bool:
        # Engine/standstill/pit/garage samples should not influence lap analysis.
        return self.is_hard_garage_sample(s)

    def build_lap_summaries_from_rows(self, source_samples: List[Sample]) -> List[LapSummary]:
        by_lap = {}
        for s in source_samples:
            if s.lap_number <= 0:
                continue
            by_lap.setdefault(s.lap_number, []).append(s)
        summaries: List[LapSummary] = []
        for lap in sorted(by_lap):
            rows = by_lap[lap]
            valid = [r for r in rows if not self.is_non_driving_sample(r) and r.lap_dist_m >= 0]
            if valid:
                start_m = min(r.lap_dist_m for r in valid)
                end_m = max(r.lap_dist_m for r in valid)
                coverage = end_m - start_m
                speeds = [r.speed_kmh for r in valid]
                brakes = [r.brake for r in valid]
                thrs = [r.throttle for r in valid]
                fuel_start = max(r.fuel_l for r in valid)
                fuel_end = min(r.fuel_l for r in valid)
                fuel_used = max(0.0, fuel_start - fuel_end)
                official_sim_time = self.sim_official_lap_time_for_lap_from_rows(source_samples, lap)
                if official_sim_time > 0:
                    duration = official_sim_time
                else:
                    times = [r.current_lap_time for r in valid if r.current_lap_time >= 0]
                    duration = (max(times) - min(times)) if times else 0.0
                    # If the sim resets/duplicates time fields, fall back to timestamp span.
                    if duration < 1.0 and len(valid) > 10:
                        try:
                            dt0 = datetime.fromisoformat(valid[0].timestamp)
                            dt1 = datetime.fromisoformat(valid[-1].timestamp)
                            duration = max(0.0, (dt1 - dt0).total_seconds())
                        except Exception:
                            pass
                min_speed = min(speeds); max_speed = max(speeds); avg_speed = sum(speeds)/len(speeds)
                max_brake = max(brakes); avg_thr = sum(thrs)/len(thrs)
            else:
                start_m = end_m = coverage = duration = min_speed = max_speed = avg_speed = max_brake = avg_thr = fuel_start = fuel_end = fuel_used = official_sim_time = 0.0
            invalidated = any(r.lap_invalidated for r in rows)
            in_pits = any(r.in_pits for r in rows)
            has_standstill = any(self.is_non_driving_sample(r) for r in rows)
            # Robust full-lap check, now dynamic for short and long circuits.
            # 3.3 used Monza-style hard limits (~5400 m), which was too strict for Silverstone National.
            session_track_m = max([r.lap_dist_m for rr in by_lap.values() for r in rr if r.lap_dist_m >= 0] or [0.0])
            if session_track_m <= 0:
                session_track_m = max(end_m, 1.0)
            start_tolerance = max(80.0, session_track_m * 0.04)
            finish_tolerance = max(90.0, session_track_m * 0.05)
            coverage_needed = max(session_track_m * 0.88, session_track_m - max(180.0, session_track_m * 0.07))
            # 0.4.5.1: Long tracks with low/variable Shared-Memory polling must not be
            # rejected just because the timer delivered fewer samples. On Sarthe, a
            # real 3:3x lap can have only ~300 usable rows.
            min_samples_needed = max(80, int(session_track_m / 50.0))
            if official_sim_time > 0:
                min_samples_needed = max(60, int(session_track_m / 65.0))
            near_start = start_m <= start_tolerance
            near_finish = end_m >= max(0.0, session_track_m - finish_tolerance)
            is_complete = near_start and near_finish and coverage >= coverage_needed and len(valid) >= min_samples_needed
            reasons = []
            if not valid:
                reasons.append("keine Fahrdaten")
            if not is_complete:
                reasons.append("nicht komplett/Outlap")
            if invalidated:
                # 0.2.4: Grund ausweisen. RaceRoom liefert die Ursache nicht per Shared Memory,
                # aber die Position des Flags schon - meist Streckenbegrenzung/Cut/Sprung.
                first_inv = next((r for r in rows if r.lap_invalidated), None)
                if first_inv is not None and getattr(first_inv, "lap_dist_m", -1) >= 0:
                    reasons.append(f"invalidiert ab {first_inv.lap_dist_m:.0f} m (Grund nicht im Shared Memory, meist Cut/Streckenbegrenzung)")
                else:
                    reasons.append("invalidiert (Grund nicht im Shared Memory, meist Cut/Streckenbegrenzung)")
            if in_pits:
                reasons.append("Pit")
            if has_standstill and not is_complete:
                reasons.append("Standphase")
            is_clean = bool(valid) and is_complete and not invalidated and not in_pits
            if is_clean:
                reasons.append("gültig")
            summaries.append(LapSummary(
                lap_number=lap, samples=len(rows), valid_samples=len(valid), start_m=start_m, end_m=end_m,
                coverage_m=coverage, duration_s=duration, min_speed=min_speed, max_speed=max_speed, avg_speed=avg_speed,
                max_brake=max_brake, avg_throttle=avg_thr, fuel_start_l=fuel_start, fuel_end_l=fuel_end,
                fuel_used_l=fuel_used, invalidated=invalidated, in_pits=in_pits, has_standstill=has_standstill,
                is_complete=is_complete, is_clean=is_clean, reason=", ".join(reasons)
            ))
        return summaries

    def build_lap_summaries(self) -> List[LapSummary]:
        return self.build_lap_summaries_from_rows(self.samples)

    def lap_samples_valid(self, lap_number: int) -> List[Sample]:
        return [s for s in self.samples if s.lap_number == lap_number and not self.is_non_driving_sample(s) and s.lap_dist_m >= 0]

    def lap_sector_overview(self, lap: LapSummary) -> Tuple[float, float, float, float, float, float, float]:
        """Stable lap overview sectors for the UI.

        RaceRoom exposes official timing internally, but not reliably in the telemetry rows we use here.
        4.4.5 therefore shows stable *interne Streckendrittel*: we sum our existing speed-based
        50-m segment times by lap distance. This avoids broken current_lap_time snapshots and keeps
        S1/S2/S3 consistent with the reference/coach calculations.
        """
        duration = self.lap_time_for_report(lap)
        if duration <= 0:
            duration = self.estimated_lap_time_from_speed(lap.lap_number)
        if duration >= 999998.0 or duration <= 0:
            duration = lap.duration_s
        segs = self.build_segment_summaries_for_lap(lap.lap_number)
        if not segs or duration <= 0:
            return 0.0, 0.0, 0.0, duration, lap.min_speed, lap.max_speed, lap.avg_speed
        track_len = max([l.end_m for l in self.lap_summaries if l.is_clean and l.end_m > 0] or [lap.end_m, 1.0])
        b1, b2 = track_len / 3.0, 2.0 * track_len / 3.0
        s1 = s2 = s3 = 0.0
        for key, seg in segs.items():
            mid = (seg.start_m + seg.end_m) / 2.0
            if mid < b1:
                s1 += seg.seg_time_s
            elif mid < b2:
                s2 += seg.seg_time_s
            else:
                s3 += seg.seg_time_s
        total = s1 + s2 + s3
        if total > 0 and abs(total - duration) > max(1.5, duration * 0.05):
            scale = duration / total
            s1 *= scale; s2 *= scale; s3 *= scale
        if min(s1, s2, s3) <= 0.1:
            s1 = duration / 3.0; s2 = duration / 3.0; s3 = duration / 3.0
        return s1, s2, s3, duration, lap.min_speed, lap.max_speed, lap.avg_speed

    def update_lap_overview_table(self):
        if not hasattr(self, "lap_overview_table"):
            return
        self.lap_overview_table.setRowCount(0)
        rows = []
        for lap in self.lap_summaries:
            s1, s2, s3, dur, mn, mx, avg = self.lap_sector_overview(lap)
            rows.append((lap, s1, s2, s3, dur, mn, mx, avg))
        if not rows:
            return
        clean_rows = [r for r in rows if r[0].is_clean]
        best_low = {}
        worst_low = {}
        best_high = {}
        worst_high = {}
        # Niedriger ist besser: Sektoren und Rundenzeit.
        for idx in [1,2,3,4]:
            vals = [r[idx] for r in clean_rows if r[idx] > 0]
            if vals:
                best_low[idx] = min(vals); worst_low[idx] = max(vals)
        # Höher ist besser: Min/Max/Durchschnitt Speed.
        for idx in [5,6,7]:
            vals = [r[idx] for r in clean_rows if r[idx] > 0]
            if vals:
                best_high[idx] = max(vals); worst_high[idx] = min(vals)
        for lap, s1, s2, s3, dur, mn, mx, avg in rows:
            row = self.lap_overview_table.rowCount(); self.lap_overview_table.insertRow(row)
            # 0.2.4: Unvollständige Runden zeigen keine übernommene Zeit mehr
            # (Runde 11 stand mit der Zeit von Runde 10 in der Tabelle).
            if not lap.is_complete:
                vals = [f"Lap #{lap.lap_number}", "—", "—", "—", "—", f"{mn:.2f}", f"{mx:.2f}", f"{avg:.2f}"]
            else:
                vals = [f"Lap #{lap.lap_number}", fmt_lap_time(s1), fmt_lap_time(s2), fmt_lap_time(s3), fmt_lap_time(dur), f"{mn:.2f}", f"{mx:.2f}", f"{avg:.2f}"]
            raw = [None, s1, s2, s3, dur, mn, mx, avg]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                if not lap.is_clean:
                    item.setBackground(QColor(120, 80, 80, 120))
                elif self.reference_lap and lap.lap_number == self.reference_lap.lap_number and c == 0:
                    item.setBackground(QColor(80, 120, 80, 160))
                    item.setText(f"Lap #{lap.lap_number} REF")
                elif c in [1,2,3,4]:
                    if c in best_low and abs(raw[c] - best_low[c]) < 0.001:
                        item.setBackground(QColor(85, 150, 95, 170))
                    elif c in worst_low and abs(raw[c] - worst_low[c]) < 0.001:
                        item.setBackground(QColor(160, 85, 85, 160))
                elif c in [5,6,7]:
                    if c in best_high and abs(raw[c] - best_high[c]) < 0.001:
                        item.setBackground(QColor(85, 150, 95, 170))
                    elif c in worst_high and abs(raw[c] - worst_high[c]) < 0.001:
                        item.setBackground(QColor(160, 85, 85, 160))
                self.lap_overview_table.setItem(row, c, item)
        self.lap_overview_table.resizeColumnsToContents()

    def lap_eval_ok(self, lap) -> bool:
        """0.2.31: Zaehlt eine Runde als auswertbar, wenn sie sauber ist ODER
        wenn 'Ungültige Runden in Auswertung' aktiviert ist (dann muessen sie
        mindestens komplett gefahren sein). Ungueltige = z. B. Track-Limits
        (Runde abgewinkelt), die Fahrdaten sind trotzdem brauchbar."""
        if getattr(lap, "is_clean", False):
            return True
        return bool(getattr(self, "include_invalid_laps", False)) and bool(getattr(lap, "is_complete", False))

    def toggle_include_invalid_laps(self, checked: bool):
        """0.2.31: 'Ungültige Runden in Auswertung' - wirkt auf Referenzwahl,
        Rundenauswahl-Combos, Vergleichsrunden, Sektor-/Zonen-Auswertung und
        Auto-Bestlap-Export. Nach dem Umschalten alles neu rechnen."""
        self.include_invalid_laps = bool(checked)
        save_analysis_config({"include_invalid_laps": self.include_invalid_laps})
        self.log.append(
            "Ungültige Runden " + ("IN der Auswertung (inkl. Referenz/Vergleich). Achtung: abgewinkelte Runden verfälschen Referenz-Vergleiche." if self.include_invalid_laps
            else "wieder AUS der Auswertung entfernt (nur saubere Runden).")
        )
        try:
            if self.samples:
                self.update_laps()
                self.update_segments()
                self.update_lap_compare()
                self.update_heatmap()
                self.update_telemetry_view()
                self.update_coach_text()
                self.update_input_coach()
                self.refresh_dashboard()
        except Exception as e:
            self.log.append(f"Neuberechnung nach Runden-Filterwechsel fehlgeschlagen: {type(e).__name__}: {e}")

    def update_laps(self):
        self.lap_summaries = self.build_lap_summaries()
        clean = [l for l in self.lap_summaries if self.lap_eval_ok(l)]  # 0.2.31: optional inkl. ungültiger Runden
        # 3.7: Auto reference can be overridden manually.
        manual_ref = self.lap_by_number(self.manual_reference_lap)
        # 0.2.4: Manuelle Referenz muss sauber sein - keine ungültige Runde als Referenz.
        # 0.2.31: ... es sei denn, 'Ungültige Runden in Auswertung' ist aktiviert.
        if manual_ref is not None and not self.lap_eval_ok(manual_ref):
            self.log.append(f"Manuell gewählte Referenz Lap {manual_ref.lap_number} ist nicht sauber ({manual_ref.reason}) - Referenz ignoriert, Auto-Referenz wird genutzt.")
            manual_ref = None
        self.reference_lap = manual_ref or (min(clean, key=lambda l: self.estimated_lap_time_from_speed(l.lap_number)) if clean else None)
        self.update_lap_overview_table()
        self.update_live_lap_table()  # 0.2.11
        self.laps_table.setRowCount(0)
        for lap in self.lap_summaries:
            row = self.laps_table.rowCount(); self.laps_table.insertRow(row)
            status = "REFERENZ" if self.reference_lap and lap.lap_number == self.reference_lap.lap_number else ("gültig" if lap.is_clean else ("ungültig (einbezogen)" if self.include_invalid_laps else "ausgeschlossen"))
            ch = self.telemetry_channels_active()
            vals = [
                lap.lap_number, status, lap.reason, lap.samples, f"{lap.coverage_m:.1f}",
                fmt_lap_time(self.lap_time_for_report(lap)) if lap.is_complete else "— (unvollständig)",
                f"{lap.max_speed:.1f}", f"{lap.avg_speed:.1f}", f"{lap.max_brake:.3f}",
                f"{lap.fuel_used_l:.3f}" if ch["fuel"] else "— (Spiel aus)",
                f"{lap.start_m:.1f}", f"{lap.end_m:.1f}",
                f"stand={int(lap.has_standstill)} pit={int(lap.in_pits)}"
            ]
            for c, v in enumerate(vals):
                self.laps_table.setItem(row, c, QTableWidgetItem(str(v)))
        self.laps_table.resizeColumnsToContents()
        self.refresh_lap_combos()
        if self.reference_lap:
            mode = "manuell" if self.manual_reference_lap == self.reference_lap.lap_number else "Auto"
            self.log.append(f"Referenzrunde erkannt ({mode}): Lap {self.reference_lap.lap_number} | Avg {self.reference_lap.avg_speed:.1f} km/h | Fuel {self.reference_lap.fuel_used_l:.2f} L")
        else:
            self.log.append("Keine komplette saubere Referenzrunde erkannt. Bitte mindestens eine volle fliegende Runde aufzeichnen.")

    def update_live_lap_table(self):
        """0.2.11: kompakte Rundenliste in der Live-Ansicht im Results-Vorbild:
        Zeit/S1/S2/S3 farbcodiert (gruen = beste, rot = schwaecheste saubere Runde),
        Gap zur besten Runde, Fuel am Rundenende."""
        if not hasattr(self, "live_lap_table"):
            return
        self.live_lap_table.setRowCount(0)
        rows = []
        for lap in self.lap_summaries:
            s1, s2, s3, dur, mn, mx, avg = self.lap_sector_overview(lap)
            rows.append((lap, s1, s2, s3, dur))
        if not rows:
            return
        clean_rows = [r for r in rows if r[0].is_clean and r[0].is_complete]
        bests = {}
        worsts = {}
        for idx in (1, 2, 3, 4):
            vals = [r[idx] for r in clean_rows if r[idx] > 0]
            if vals:
                bests[idx] = min(vals)
                worsts[idx] = max(vals)
        cand = [r for r in clean_rows if r[4] > 0]
        best = min(cand, key=lambda r: r[4]) if cand else None
        best_no = best[0].lap_number if best else None
        best_dur = best[4] if best else 0.0
        for lap, s1, s2, s3, dur in rows:
            row = self.live_lap_table.rowCount(); self.live_lap_table.insertRow(row)
            if not lap.is_complete:
                vals = ["Lap %d" % lap.lap_number, "\u2014", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014"]
                raw = [None, 0.0, 0.0, 0.0, 0.0, None, None]
            else:
                gap = (dur - best_dur) if (lap.is_clean and best_dur > 0 and dur > 0) else None
                fuel_end = float(getattr(lap, "fuel_end_l", 0.0) or 0.0)
                vals = [
                    "Lap %d" % lap.lap_number,
                    fmt_lap_time(dur), fmt_lap_time(s1), fmt_lap_time(s2), fmt_lap_time(s3),
                    (fmt_lap_time(gap, signed=True) if gap is not None else "\u2014"),
                    ("%.1f" % fuel_end if fuel_end > 0 else "\u2014"),
                ]
                raw = [None, s1, s2, s3, dur, gap, None]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                if not lap.is_clean:
                    item.setBackground(QColor(120, 80, 80, 120))
                elif best_no is not None and lap.lap_number == best_no:
                    item.setBackground(QColor(80, 120, 80, 160))
                elif c in (1, 2, 3, 4) and raw[c] and raw[c] > 0:
                    if c in bests and abs(raw[c] - bests[c]) < 0.001:
                        item.setBackground(QColor(85, 150, 95, 170))
                    elif c in worsts and abs(raw[c] - worsts[c]) < 0.001:
                        item.setBackground(QColor(160, 85, 85, 160))
                if best_no is not None and lap.lap_number == best_no and c == 0:
                    item.setText("Lap %d BEST" % lap.lap_number)
                self.live_lap_table.setItem(row, c, item)
        self.live_lap_table.resizeColumnsToContents()

    def _remember_session(self, path):
        """0.2.13: gespeicherten Report in den Sitzungs-Index uebernehmen
        (Strecke/Fahrzeug/Runden/Bestzeit fuer den Sitzungs-Browser)."""
        try:
            idx = load_sessions_index()
            meta = idx.setdefault("meta", {}) if isinstance(idx, dict) else {}
            last = self.samples[-1] if self.samples else None
            laps = [l for l in (getattr(self, "lap_summaries", None) or [])]
            clean = [l for l in laps if l.is_clean and l.is_complete]
            best = ""
            if clean:
                best = fmt_lap_time(min(self.estimated_lap_time_from_speed(l.lap_number) for l in clean))
            veh = ""
            if self.recording_signature:
                veh = self.sample_vehicle_label(self.recording_signature)
            if (not veh) and last is not None:
                veh = str(getattr(last, "vehicle_name", "") or "")
            meta[str(Path(path).name)] = {
                "datum": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "track": (str(getattr(last, "track", "") or "") if last is not None else ""),
                "vehicle": str(veh or ""),
                "runden": len(laps),
                "bestzeit": str(best),
            }
            save_sessions_index(idx)
        except Exception:
            pass

    def refresh_sessions_table(self):
        """0.2.13: gespeicherte Reports im Sitzungs-Browser listen."""
        if not hasattr(self, "sessions_table"):
            return
        self.sessions_table.setRowCount(0)
        idx = load_sessions_index()
        names = idx.get("names", {}) if isinstance(idx, dict) else {}
        meta = idx.get("meta", {}) if isinstance(idx, dict) else {}
        try:
            files = sorted(REPORT_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            files = []
        import re as _re
        changed = False  # 0.2.15: Rueckfuellung aelterer Sitzungen in sessions.json
        for p in files:
            m = meta.get(p.name, {})
            if not isinstance(m, dict):
                m = {}
            if not (m.get("track") or m.get("vehicle") or m.get("runden") or m.get("bestzeit")):
                parsed = parse_session_report_meta(p)
                if parsed:
                    m = dict(parsed)
                    meta[p.name] = m
                    changed = True
            dm = _re.match(r"r3e_live_recorder_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", p.name)
            datum = str(m.get("datum", "") or "")
            if (not datum) and dm:
                datum = dm.group(3) + "." + dm.group(2) + "." + dm.group(1) + " " + dm.group(4) + ":" + dm.group(5)
            if not datum:
                datum = "\u2014"
            vals = [
                datum,
                str(names.get(p.name, "") or ""),
                str(m.get("track", "") or ""),
                str(m.get("vehicle", "") or ""),
                (str(m.get("runden", "")) if m.get("runden", "") != "" else ""),
                str(m.get("bestzeit", "") or ""),
            ]
            row = self.sessions_table.rowCount(); self.sessions_table.insertRow(row)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignCenter)
                it.setData(Qt.UserRole, str(p))
                self.sessions_table.setItem(row, c, it)
        if changed:  # 0.2.15: einmalig ausgelesene Metadaten dauerhaft merken
            idx["meta"] = meta
            save_sessions_index(idx)
        self.sessions_table.resizeColumnsToContents()

    def _selected_session_file(self):
        if not hasattr(self, "sessions_table"):
            return None
        r = self.sessions_table.currentRow()
        if r < 0:
            return None
        it = self.sessions_table.item(r, 0)
        if it is None:
            return None
        p = it.data(Qt.UserRole)
        return Path(p) if p else None

    def open_session_report(self):
        """0.2.13: gespeicherten Report in einem Fenster anzeigen (Doppelklick)."""
        p = self._selected_session_file()
        if p is None or not p.is_file():
            self.status.setText("Sitzungen: keine Zeile markiert.")
            return
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            QMessageBox.warning(self, "Sitzungen", "Report konnte nicht gelesen werden: " + str(e))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Sitzung: " + p.stem)
        dlg.resize(860, 640)
        lay = QVBoxLayout(dlg)
        view = QTextEdit(); view.setReadOnly(True)
        view.setPlainText(txt)
        lay.addWidget(view, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.show()

    def rename_session(self):
        """0.2.13: eigenen Namen fuer eine Aufzeichnung (sessions.json, Datei unangetastet)."""
        p = self._selected_session_file()
        if p is None:
            self.status.setText("Sitzungen: keine Zeile markiert.")
            return
        idx = load_sessions_index()
        names = idx.setdefault("names", {}) if isinstance(idx, dict) else {}
        dlg = QDialog(self)
        dlg.setWindowTitle("Sitzung umbenennen")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Eigener Name f\u00fcr diese Aufzeichnung:"))
        edit = QLineEdit(str(names.get(p.name, p.stem) or ""))
        lay.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.Accepted:
            names[p.name] = edit.text().strip()
            save_sessions_index(idx)
            self.refresh_sessions_table()

    def delete_session(self):
        """0.2.16: gespeicherte Sitzung loeschen (Report-Datei + passende CSV + Index-Eintraege)."""
        p = self._selected_session_file()
        if p is None or not p.is_file():
            self.status.setText("Sitzungen: keine Zeile markiert.")
            return
        msg = ("Diese Aufzeichnung wirklich löschen?\n\n" + p.name +
               "\n\nDie zugehörige CSV wird mitgelöscht. Das kann nicht rückgängig gemacht werden.")
        if QMessageBox.question(self, "Sitzung löschen", msg) != QMessageBox.Yes:
            return
        try:
            p.unlink()
        except Exception as e:
            QMessageBox.warning(self, "Sitzung löschen", "Datei konnte nicht gelöscht werden: " + str(e))
            return
        # 0.2.16: passende CSV (gleicher Zeitstempel) mitloeschen
        csv_candidate = CSV_DIR / ("r3e_live_recorder_samples_" + p.stem.replace("r3e_live_recorder_", "", 1) + ".csv")
        try:
            if csv_candidate.is_file():
                csv_candidate.unlink()
        except Exception:
            pass
        # 0.2.16: Eintraege aus dem Sitzungs-Index entfernen
        idx = load_sessions_index()
        names = idx.get("names", {}) if isinstance(idx, dict) else {}
        meta = idx.get("meta", {}) if isinstance(idx, dict) else {}
        names.pop(p.name, None)
        meta.pop(p.name, None)
        save_sessions_index(idx)
        self.refresh_sessions_table()
        self.status.setText("Sitzung gelöscht: " + p.name)

    def load_session_into_views(self):
        """0.2.17: alte Aufzeichnung aus der zugehoerigen CSV in die Live-Ansicht
        laden, damit Reifen/Analyse/Runden/Vergleich/Heatmap die alte Sitzung zeigen."""
        p = self._selected_session_file()
        if p is None:
            self.status.setText("Sitzungen: keine Zeile markiert.")
            return
        if self.recording:
            QMessageBox.warning(self, "Sitzung laden", "Recording läuft gerade. Bitte erst stoppen (F8), danach laden.")
            return
        stamp = p.stem.replace("r3e_live_recorder_", "", 1)
        csv_path = CSV_DIR / ("r3e_live_recorder_samples_" + stamp + ".csv")
        if not csv_path.is_file():
            QMessageBox.warning(self, "Sitzung laden", "Zu dieser Aufzeichnung fehlt die CSV (r3e_live_recorder_samples_" + stamp + "). Ohne CSV können die Reiter nicht gefüllt werden.")
            return
        msg = ("Diese Aufzeichnung in die Ansicht laden?\n\n" + p.name +
               "\n\nDer aktuelle Datenpuffer wird im Programm ersetzt - Dateien bleiben unberührt.")
        if QMessageBox.question(self, "Sitzung laden", msg) != QMessageBox.Yes:
            return
        try:
            samples = load_samples_from_csv(csv_path)
        except Exception as e:
            QMessageBox.warning(self, "Sitzung laden", "CSV konnte nicht gelesen werden: " + str(e))
            return
        if not samples:
            QMessageBox.warning(self, "Sitzung laden", "CSV enthält keine Samples.")
            return
        self.samples = samples
        self.last_live_sample = samples[-1]  # Live-Karten/Reifen-Tab mit altem Stand füllen
        self.recording_signature = None
        self.manual_reference_lap = None
        self.manual_compare_lap = None
        self.compare_lap = None
        self.update_laps()  # Referenz + Runden-/Live-Runden-Tabellen
        ref_samples = self.samples_for_reference_lap()
        self.trackmap.set_samples(ref_samples if ref_samples else self.samples)
        self.trackmap.set_sector_info(self.official_sector_bounds())
        self.update_segments()
        self.update_lap_compare()
        self.update_heatmap()
        self.update_telemetry_view()  # 0.2.21
        self.update_zone_table()
        self.update_input_coach()
        self.update_coach_text()
        self.status.setText("Alte Sitzung geladen: " + p.name + " (" + str(len(samples)) + " Samples)")
        self.log.append("Sitzung aus CSV geladen: " + p.name + " | Samples: " + str(len(samples)))

    def update_segments(self):
        self.segment_table.setRowCount(0)
        if not self.samples:
            return
        source = self.samples_for_reference_lap() or [s for s in self.samples if not self.is_non_driving_sample(s)]
        buckets = {}
        for s in source:
            if s.lap_dist_m < 0:
                continue
            key = int(s.lap_dist_m // 50) * 50
            buckets.setdefault(key, []).append(s)
        for idx, key in enumerate(sorted(buckets)):
            rows = buckets[key]
            if len(rows) < 2:
                continue
            speeds = [r.speed_kmh for r in rows]
            brakes = [r.brake for r in rows]
            thrs = [r.throttle for r in rows]
            gears = [r.gear for r in rows if r.gear > 0]
            gear_common = max(set(gears), key=gears.count) if gears else "-"
            max_brake = max(brakes)
            min_speed = min(speeds)
            avg_speed = sum(speeds) / len(speeds)
            avg_thr = sum(thrs) / len(thrs)
            if max_brake > 0.25:
                hint = "Bremszone"
            elif avg_thr > 0.85:
                hint = "Vollgas"
            elif min_speed < 80:
                hint = "Langsame Passage"
            else:
                hint = "neutral"
            row = self.segment_table.rowCount(); self.segment_table.insertRow(row)
            vals = [row + 1, f"{key}-{key+50}", len(rows), f"{avg_speed:.1f}", f"{min_speed:.1f}", f"{max_brake:.3f}", f"{avg_thr:.3f}", gear_common, hint]
            for c, v in enumerate(vals):
                self.segment_table.setItem(row, c, QTableWidgetItem(str(v)))
        self.segment_table.resizeColumnsToContents()

    def samples_for_lap(self, lap_number: int) -> List[Sample]:
        rows = [s for s in self.samples if s.lap_number == lap_number and not self.is_non_driving_sample(s) and s.lap_dist_m >= 0 and s.speed_kmh > 1]
        rows.sort(key=lambda s: (s.lap_dist_m, s.timestamp))
        # Remove an occasional rollover sample at the end of the previous lap.
        while len(rows) > 2 and rows[0].lap_dist_m > 2000 and rows[1].lap_dist_m < 200:
            rows = rows[1:]
        return rows

    def build_segment_summaries_from_rows(self, rows: List[Sample], lap_number: int) -> dict:
        rows = [r for r in rows if not self.is_non_driving_sample(r) and r.lap_dist_m >= 0 and r.speed_kmh > 1]
        rows.sort(key=lambda s: (s.lap_dist_m, s.timestamp))
        if len(rows) < 5:
            return {}
        max_d = max(r.lap_dist_m for r in rows)
        out = {}
        # 3.5/4.1.1: Use speed-integrated segment time instead of RaceRoom current_lap_time.
        # This also allows live segment deltas without pressing Recording.
        for key in range(0, int(max_d // 50) * 50 + 1, 50):
            start_m = float(key)
            seg_rows = [r for r in rows if start_m <= r.lap_dist_m < start_m + 50]
            if len(seg_rows) < 2:
                continue
            speeds = [r.speed_kmh for r in seg_rows if r.speed_kmh > 1]
            if not speeds:
                continue
            avg_speed = sum(speeds) / len(speeds)
            if avg_speed <= 1:
                continue
            segment_len_m = max(1.0, min(50.0, max_d - start_m))
            # 0.2.4: Segmentzeit korrekt über Sample-Paare integrieren (harmonisches Mittel)
            # statt Länge / Ø-Speed (arithmetisch). Letzteres überschätzt die Zeit
            # systematisch und machte die Zonensummen nicht nachrechenbar.
            seg_time_s = 0.0
            end_m_eff = min(start_m + 50.0, max_d)
            first_r, last_r = seg_rows[0], seg_rows[-1]
            if first_r.lap_dist_m > start_m:
                seg_time_s += (first_r.lap_dist_m - start_m) / max(first_r.speed_kmh, 2.0)
            _prev = None
            for _r in seg_rows:
                if _prev is not None and _r.lap_dist_m > _prev.lap_dist_m:
                    _v = max((_prev.speed_kmh + _r.speed_kmh) / 2.0, 2.0)
                    seg_time_s += (_r.lap_dist_m - _prev.lap_dist_m) / _v
                _prev = _r
            if last_r.lap_dist_m < end_m_eff and (end_m_eff - last_r.lap_dist_m) < 25.0:
                seg_time_s += (end_m_eff - last_r.lap_dist_m) / max(last_r.speed_kmh, 2.0)
            # Einheiten: Geschwindigkeit liegt in km/h; Faktor 3.6 rechnet auf m/s um
            # (dist/speed_kmh * 3.6 == dist/(speed_kmh/3.6)).
            seg_time_s *= 3.6
            if seg_time_s <= 0:
                seg_time_s = segment_len_m / (avg_speed / 3.6)
            brakes = [r.brake for r in seg_rows]
            thrs = [r.throttle for r in seg_rows]
            gears = [r.gear for r in seg_rows if r.gear > 0]
            gear_common = str(max(set(gears), key=gears.count)) if gears else "-"
            out[key] = SegmentSummary(
                lap_number=lap_number,
                start_m=key,
                end_m=key + int(segment_len_m),
                samples=len(seg_rows),
                seg_time_s=seg_time_s,
                avg_speed=avg_speed,
                min_speed=min(speeds),
                max_speed=max(speeds),
                max_brake=max(brakes),
                avg_throttle=sum(thrs) / len(thrs),
                gear_common=gear_common,
            )
        return out

    def build_segment_summaries_for_lap(self, lap_number: int) -> dict:
        return self.build_segment_summaries_from_rows(self.samples_for_lap(lap_number), lap_number)

    def estimated_lap_time_from_speed(self, lap_number: int) -> float:
        segs = self.build_segment_summaries_for_lap(lap_number)
        if not segs:
            return 999999.0
        return sum(s.seg_time_s for s in segs.values())

    def is_plausible_compare_lap(self, lap: LapSummary, ref_segments: dict, use_external: bool = False) -> Tuple[bool, str]:
        """4.0.7: Safety filter so Auto compare never picks a partial/rolling-out/standstill lap.
        External reference comparisons are especially sensitive because a partial lap can share only the first
        few 50-m sectors and produce absurd deltas like +8 s in one zone.
        """
        if not lap or not lap.is_clean:
            return False, "Runde nicht sauber"
        cmp_segments = self.build_segment_summaries_for_lap(lap.lap_number)
        if not cmp_segments:
            return False, "keine Segmentdaten"
        if not ref_segments:
            return False, "keine Referenzsegmente"
        ref_keys = set(ref_segments.keys())
        cmp_keys = set(cmp_segments.keys())
        common = ref_keys & cmp_keys
        if not ref_keys or not common:
            return False, "keine Segment-Überlappung"
        overlap_ratio = len(common) / max(1, len(ref_keys))
        ref_max_key = max(ref_keys)
        cmp_max_key = max(cmp_keys)
        # Full-lap coverage check at segment level. This catches laps that look complete in scoring,
        # but only contain the first half of usable telemetry after the recording stopped or the car stood still.
        if overlap_ratio < 0.88 or cmp_max_key < ref_max_key * 0.88:
            return False, f"Segmentabdeckung zu klein ({overlap_ratio*100:.0f}%)"
        # Fuel/sample sanity. Normal GT3 Silverstone laps use around 1.3-1.5 L in our tests; do not hardcode that,
        # but reject obviously tiny fuel use when an external/reference comparison is active.
        if use_external and lap.fuel_used_l > 0 and lap.fuel_used_l < 0.75:
            return False, "Fuel Used zu klein / vermutlich Teilrunde"
        if lap.avg_speed < 120:
            return False, "Avg Speed zu niedrig / vermutlich Standphase"
        # Segment outlier check for automatic selection. A true 50-m sector delta above 2 s is almost always
        # stopped/slow car data, not a useful driving coach signal.
        outlier_count = 0
        for key in sorted(common):
            d = cmp_segments[key].seg_time_s - ref_segments[key].seg_time_s
            if d > 2.0:
                outlier_count += 1
        if outlier_count:
            return False, "unplausibler Sektor-Ausreißer"
        return True, "ok"

    def plausible_compare_laps(self, ref_segments: dict, use_external: bool = False) -> List[LapSummary]:
        out = []
        rejected = []
        for lap in [l for l in self.lap_summaries if self.lap_eval_ok(l)]:  # 0.2.31
            if not use_external and self.reference_lap and lap.lap_number == self.reference_lap.lap_number:
                continue
            # 4.0.4.5.2: Wenn die externe Referenz gerade aus dieser Session automatisch exportiert wurde,
            # darf Auto-Vergleich nicht wieder exakt dieselbe Runde wählen. Sonst entsteht ein nutzloses +0.000 s.
            if use_external and self.auto_bestlap_lap_number and lap.lap_number == self.auto_bestlap_lap_number:
                rejected.append(f"Lap {lap.lap_number}: aktuelle Auto-Referenzrunde, nicht als Vergleich genutzt")
                continue
            ok, reason = self.is_plausible_compare_lap(lap, ref_segments, use_external=use_external)
            if ok:
                out.append(lap)
            else:
                rejected.append(f"Lap {lap.lap_number}: {reason}")
        if rejected:
            self.log.append("Auto-Vergleich Sicherheitsfilter: " + "; ".join(rejected[:4]) + (" ..." if len(rejected) > 4 else ""))
        return out

    def external_reference_segments(self) -> dict:
        if not self.external_reference:
            return {}
        out = {}
        for d in self.external_reference.get("segments", []):
            seg = self.dict_to_segment(d)
            out[seg.start_m] = seg
        return out

    def external_reference_samples(self) -> List[Sample]:
        if not self.external_reference:
            return []
        meta = self.external_reference.get("meta", {})
        rows = []
        for p in self.external_reference.get("path", []):
            rows.append(Sample(
                timestamp=meta.get("created_at", ""), game_version=0, track=meta.get("track", ""), player_name="Reference",
                active_vehicles=0, player_idx=-1, player_has_vehicle=False, telem_id=-1, scoring_id=-1,
                vehicle_name=meta.get("vehicle_name", ""), vehicle_model=meta.get("vehicle_model", ""), vehicle_class=meta.get("vehicle_class", ""),
                speed_kmh=fnum(p.get("speed_kmh")), gear=0, rpm=0.0, fuel_l=0.0, fuel_capacity_l=0.0,
                throttle=0.0, brake=0.0, steering=0.0, pos_x=fnum(p.get("pos_x")), pos_y=0.0, pos_z=fnum(p.get("pos_z")),
                lap_number=-1, completed_laps=0, lap_dist_m=fnum(p.get("lap_dist_m")), current_lap_time=0.0, last_lap_time=0.0,
                best_lap_time=0.0, lap_invalidated=False, in_pits=False, place=0
            ))
        return rows

    def build_lap_compare(self) -> List[SegmentDelta]:
        if not self.lap_summaries:
            self.update_laps()
        use_external = self.external_reference is not None and self.use_external_reference
        ref_segments = self.external_reference_segments() if use_external else {}
        if not use_external:
            if not self.reference_lap:
                self.compare_lap = None
                return []
            ref_segments = self.build_segment_summaries_for_lap(self.reference_lap.lap_number)
        clean = self.plausible_compare_laps(ref_segments, use_external=use_external)
        if not clean or not ref_segments:
            self.compare_lap = None
            self.log.append("Kein plausibler Vergleich möglich: Bitte eine vollständige fliegende Runde aufzeichnen oder manuell eine gültige Runde wählen.")
            return []
        manual_cmp = self.lap_by_number(self.manual_compare_lap)
        if manual_cmp and (use_external or (self.reference_lap and manual_cmp.lap_number != self.reference_lap.lap_number)):
            ok, reason = self.is_plausible_compare_lap(manual_cmp, ref_segments, use_external=use_external)
            if ok:
                self.compare_lap = manual_cmp
            else:
                self.compare_lap = min(clean, key=lambda l: self.estimated_lap_time_from_speed(l.lap_number))
                self.log.append(f"Manuelle Vergleichsrunde Lap {manual_cmp.lap_number} verworfen ({reason}); Auto nutzt Lap {self.compare_lap.lap_number}.")
        else:
            self.compare_lap = min(clean, key=lambda l: self.estimated_lap_time_from_speed(l.lap_number))
        cmp = self.build_segment_summaries_for_lap(self.compare_lap.lap_number)
        deltas: List[SegmentDelta] = []
        for key in sorted(set(ref_segments) & set(cmp)):
            r = ref_segments[key]
            c = cmp[key]
            delta = c.seg_time_s - r.seg_time_s
            speed_delta = c.avg_speed - r.avg_speed
            brake_delta = c.max_brake - r.max_brake
            throttle_delta = c.avg_throttle - r.avg_throttle
            if delta > 0.15 and c.max_brake > r.max_brake + 0.08:
                hint = "Zeitverlust: stärker/länger gebremst"
            elif delta > 0.15 and c.avg_throttle < r.avg_throttle - 0.12:
                hint = "Zeitverlust: später/weniger Gas"
            elif delta > 0.15 and c.avg_speed < r.avg_speed - 5:
                hint = "Zeitverlust: weniger Speed"
            elif delta < -0.10:
                hint = "besser als Referenz"
            elif c.max_brake > 0.25 or r.max_brake > 0.25:
                hint = "Bremszone ähnlich"
            elif c.avg_throttle > 0.85 and r.avg_throttle > 0.85:
                hint = "Vollgas ähnlich"
            else:
                hint = "neutral"
            deltas.append(SegmentDelta(
                start_m=key, end_m=key + 50,
                compare_lap=self.compare_lap.lap_number, reference_lap=(-1 if use_external else self.reference_lap.lap_number),
                cmp_time_s=c.seg_time_s, ref_time_s=r.seg_time_s, delta_s=delta,
                cmp_avg_speed=c.avg_speed, ref_avg_speed=r.avg_speed, speed_delta=speed_delta,
                cmp_max_brake=c.max_brake, ref_max_brake=r.max_brake, brake_delta=brake_delta,
                cmp_avg_throttle=c.avg_throttle, ref_avg_throttle=r.avg_throttle, throttle_delta=throttle_delta,
                hint=hint,
            ))
        return deltas

    def update_lap_compare(self):
        self.compare_table.setRowCount(0)
        self.segment_deltas = self.build_lap_compare()
        for d in self.segment_deltas:
            row = self.compare_table.rowCount(); self.compare_table.insertRow(row)
            vals = [
                row + 1, f"{d.start_m}-{d.end_m}", f"Lap {d.compare_lap}", ("Extern" if d.reference_lap < 0 else f"Lap {d.reference_lap}"),
                f"{d.delta_s:+.3f}", fmt_lap_time(d.cmp_time_s), fmt_lap_time(d.ref_time_s),
                f"{d.cmp_avg_speed:.1f}", f"{d.ref_avg_speed:.1f}", f"{d.speed_delta:+.1f}",
                f"{d.brake_delta:+.3f}", f"{d.throttle_delta:+.3f}", d.hint
            ]
            for c, v in enumerate(vals):
                self.compare_table.setItem(row, c, QTableWidgetItem(str(v)))
        self.compare_table.resizeColumnsToContents()
        if (self.reference_lap or self.external_reference) and self.compare_lap:
            total = sum(d.delta_s for d in self.segment_deltas)
            self.log.append(f"Rundenvergleich: Lap {self.compare_lap.lap_number} vs {self.reference_display_label()} | Segment-Delta gesamt {total:+.3f} s")
        elif self.reference_lap or self.external_reference:
            self.log.append("Rundenvergleich: keine gültige Vergleichsrunde vorhanden.")
        self.update_zone_table()

    def official_sector_bounds(self) -> List[float]:
        """0.2.9: haeufigste offizielle Sektorgrenzen (Meter) aus den Samples.

        Das Spiel liefert sector_start_factors (Anteil der Streckenlaenge); der Reader
        macht daraus innere Grenzen in Metern. Kleine Rundungsunterschiede zwischen
        Samples werden auf 10 m dedupliziert. Rueckgabe: [] = keine gueltigen Werte,
        dann bleibt das 50-m-Raster die Grundlage."""
        counts = {}
        for s in self.samples:
            b = getattr(s, "sector_bounds_m", None) or ()
            if len(b) >= 2:
                key = tuple(int(round(float(x) / 10.0)) for x in b[:2])
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return []
        key = max(counts.items(), key=lambda kv: kv[1])[0]
        return [k * 10.0 for k in key]

    def sector_name_for_m(self, m: float) -> str:
        """0.2.9: offizieller Sektor (S1/S2/S3) fuer eine Meter-Position; '' = Grenzen unbekannt."""
        b = self.official_sector_bounds()
        if len(b) >= 2:
            if m < float(b[0]):
                return "S1"
            if m < float(b[1]):
                return "S2"
            return "S3"
        return ""

    def lap_compare_report_lines(self) -> List[str]:
        if not self.segment_deltas:
            self.update_lap_compare()
        lines = ["", "Lap-vs-Referenz-Vergleich 50 m:"]
        if not self.reference_lap and not self.external_reference:
            lines.append("Keine Referenzrunde vorhanden.")
            return lines
        if not self.compare_lap:
            lines.append("Keine zweite gültige Runde für Vergleich vorhanden.")
            return lines
        total = sum(d.delta_s for d in self.segment_deltas)
        losses = [d for d in self.segment_deltas if d.delta_s > 0.10]
        gains = [d for d in self.segment_deltas if d.delta_s < -0.10]
        lines.append(f"Vergleich: Lap {self.compare_lap.lap_number} gegen {self.reference_display_label()} | Segment-Delta gesamt {total:+.3f} s")
        lines.append(f"Problemzonen: {len(losses)} | bessere Zonen: {len(gains)}")
        warn = self.start_finish_warning()
        if warn:
            lines.append(warn)
        lines.append("Sektor | Meter | Delta s | Vgl Zeit [m]:ss.000* | Ref Zeit [m]:ss.000* | Vgl Avg | Ref Avg | Speed Diff | Brake Diff | Throttle Diff | Hinweis")
        for idx, d in enumerate(self.segment_deltas, 1):
            if abs(d.delta_s) >= 0.05 or "Zeitverlust" in d.hint:
                lines.append(
                    f"{idx} | {d.start_m}-{d.end_m} | {d.delta_s:+.3f} | {fmt_lap_time(d.cmp_time_s)} | {fmt_lap_time(d.ref_time_s)} | "
                    f"{d.cmp_avg_speed:.1f} | {d.ref_avg_speed:.1f} | {d.speed_delta:+.1f} | "
                    f"{d.brake_delta:+.3f} | {d.throttle_delta:+.3f} | {d.hint}"
                )
        top_losses = sorted(losses, key=lambda d: d.delta_s, reverse=True)[:8]
        lines.append("")
        lines.append("Top-Einzelsektoren:")
        if not top_losses:
            lines.append("Keine einzelnen Problemsektoren > +0.10 s erkannt.")
        for d in top_losses:
            lines.append(f"{d.start_m}-{d.end_m} m: {d.delta_s:+.3f} s | {d.hint} | Speed {d.speed_delta:+.1f} km/h | Brake {d.brake_delta:+.3f} | Gas {d.throttle_delta:+.3f}")

        grouped = self.grouped_problem_zones()
        lines.append("")
        lines.append("Zusammenhängende Problemzonen:")
        if not grouped:
            lines.append("Keine zusammenhängende Problemzone erkannt.")
        for i, (start, end, total_loss, spd, brk, thr, cause, advice) in enumerate(grouped[:8], 1):
            sec = self.sector_name_for_m(start)  # 0.2.9: offizieller Sektor der Zone
            sec_txt = f" ({sec})" if sec else ""
            lines.append(f"{i}. {start}-{end} m{sec_txt} | Summe {total_loss:+.3f} s | {cause} | Speed {spd:+.1f} km/h | Brake {brk:+.3f} | Gas {thr:+.3f}")

        # 0.2.9: offizielle Spiel-Sektoren (sector_start_factors) statt nur schematischem Raster
        bounds = self.official_sector_bounds()
        lines.append("")
        if len(bounds) >= 2:
            lines.append("Offizielle Sektoren (aus dem Spiel, sector_start_factors):")
            end_m = max((d.end_m for d in self.segment_deltas), default=0.0)
            edges = [0.0, float(bounds[0]), float(bounds[1]), float(end_m)]
            for si in range(3):
                s0, s1 = edges[si], edges[si + 1]
                segs = [d for d in self.segment_deltas if s0 - 1e-6 <= d.start_m < s1]
                if not segs:
                    continue
                tot = sum(d.delta_s for d in segs)
                spd = sum(d.speed_delta for d in segs) / len(segs)
                lines.append(f"Sektor {si + 1} | {int(round(s0))}-{int(round(s1))} m | Delta {tot:+.3f} s | Ø Speed-Diff {spd:+.1f} km/h")
        else:
            lines.append("Offizielle Sektoren: Spiel liefert keine gueltigen Sektorgrenzen (sector_start_factors) - 50-m-Raster bleibt Grundlage.")
        return lines


    def grouped_problem_zones(self) -> List[Tuple[int, int, float, float, float, float, str, str]]:
        """Group adjacent weak losing 50-m sectors into human-readable coach zones.

        3.8 is intentionally more aggressive than 3.7: several small +0.04 to +0.09 s
        losses in the same braking/corner phase are more useful than one isolated sector.
        Returns: start, end, total_delta, avg_speed_delta, max_brake_delta, avg_throttle_delta, cause, advice
        """
        if not self.segment_deltas:
            self.segment_deltas = self.build_lap_compare()
        # Include smaller positive deltas so a whole corner phase is recognized.
        candidates = [d for d in self.segment_deltas if d.delta_s > 0.035]
        if not candidates:
            return []
        candidates = sorted(candidates, key=lambda d: d.start_m)
        groups = []
        current = [candidates[0]]
        for d in candidates[1:]:
            prev = current[-1]
            # Allow a small gap so a real corner phase stays together even if one 50-m bucket is neutral.
            if d.start_m <= prev.end_m + 100:
                current.append(d)
            else:
                groups.append(current)
                current = [d]
        groups.append(current)

        out = []
        for g in groups:
            positive = [d for d in g if d.delta_s > 0]
            if not positive:
                continue
            start = min(d.start_m for d in g)
            end = max(d.end_m for d in g)
            total = sum(max(0.0, d.delta_s) for d in g)
            # Filter tiny one-off noise, but keep multi-sector corner phases.
            if total < 0.10 and len(g) < 2:
                continue
            if total < 0.14 and len(g) < 3:
                continue
            spd = sum(d.speed_delta for d in g) / len(g)
            brk = max(d.brake_delta for d in g)
            thr = sum(d.throttle_delta for d in g) / len(g)
            max_ref_brake = max(d.ref_max_brake for d in g)
            max_cmp_brake = max(d.cmp_max_brake for d in g)
            avg_cmp_thr = sum(d.cmp_avg_throttle for d in g) / len(g)
            avg_ref_thr = sum(d.ref_avg_throttle for d in g) / len(g)
            braking_zone = max_cmp_brake > 0.20 or max_ref_brake > 0.20 or brk > 0.08

            if braking_zone and brk > 0.10 and spd < -5:
                cause = "Bremsphase kostet Zeit"
                advice = "Bremse früher und sauberer lösen; Auto in die Kurve rollen lassen statt Speed zu stark abzubauen."
            elif braking_zone and spd < -8:
                cause = "zu wenig Speed durch die Brems-/Einlenkphase"
                advice = "Bremspunkt nicht härter machen, sondern Lösepunkt und Mindesttempo stabilisieren."
            elif avg_cmp_thr < avg_ref_thr - 0.10:
                cause = "spätere oder schwächere Gasannahme"
                advice = "Auto früher gerade stellen und Gasaufbau am Ausgang früher beginnen."
            elif spd < -10:
                cause = "zu wenig Mindest-/Kurvenspeed"
                advice = "Eingang ruhiger wählen, weniger Tempo wegwerfen und sauberer durchrollen."
            elif braking_zone:
                cause = "Bremszone inkonstant"
                advice = "Bremsdruck, Lösepunkt und Einlenken reproduzierbarer treffen."
            else:
                cause = "Rhythmus-/Linienverlust"
                advice = "Linie und Lenkwinkel ruhiger halten; Referenz in diesem Bereich nachfahren."
            out.append((start, end, total, spd, brk, thr, cause, advice))
        out.sort(key=lambda x: x[2], reverse=True)
        return out

    def heatmap_report_lines(self) -> List[str]:
        lines = ["", "Trackmap-Heatmap:"]
        if (not self.reference_lap and not self.external_reference) or not self.compare_lap or not self.segment_deltas:
            lines.append("Keine Heatmap möglich: mindestens eine Referenz und eine Vergleichsrunde nötig.")
            return lines
        zones = self.grouped_problem_zones()
        losses = [d for d in self.segment_deltas if d.delta_s > 0.06]
        gains = [d for d in self.segment_deltas if d.delta_s < -0.10]
        total = sum(d.delta_s for d in self.segment_deltas)
        lines.append(f"{self.reference_display_label()} vs Vergleich Lap {self.compare_lap.lap_number} | Delta gesamt {total:+.3f} s")
        lines.append(f"Heatmap-Legende: dicke rote/orange Bereiche=Coach-Zonen ({len(zones)}), Rot/Orange=Zeitverlust ({len(losses)} Sektoren), Grün=besser ({len(gains)} Sektoren).")
        if zones:
            lines.append("Markierte Coach-Zonen auf der Map:")
            for i, z in enumerate(zones[:5], 1):
                sec = self.sector_name_for_m(z[0])  # 0.2.9: offizieller Sektor der Zone
                sec_txt = f" ({sec})" if sec else ""
                lines.append(f"Zone {i}: {z[0]}-{z[1]} m{sec_txt} | {z[2]:+.3f} s | {z[6]}")
        else:
            lines.append("Keine markierte Coach-Zone vorhanden.")
        return lines

    def coach_report_lines(self) -> List[str]:
        if not self.segment_deltas:
            self.segment_deltas = self.build_lap_compare()
        lines = ["", "Coach-Hinweise:"]
        if not self.reference_lap and not self.external_reference:
            lines.append("Keine Referenzrunde vorhanden. Erst eine Runde aufzeichnen oder externe Referenz importieren.")
            return lines
        if not self.compare_lap:
            lines.append("Keine Vergleichsrunde vorhanden. Für Coaching mindestens zwei saubere Runden aufzeichnen.")
            return lines
        total = sum(d.delta_s for d in self.segment_deltas)
        losses = self.grouped_problem_zones()
        lines.append(f"Vergleich Lap {self.compare_lap.lap_number} gegen {self.reference_display_label()}: Gesamt {total:+.3f} s.")
        warn = self.start_finish_warning()
        if warn:
            lines.append(warn)
            if len(losses) > 1 and losses[0][0] < 250:
                losses = losses[1:] + [losses[0]]
        if not losses:
            lines.append("Keine klaren zusammenhängenden Problemzonen erkannt. Fokus: Konstanz halten und mehr Runden sammeln.")
            return lines
        lines.append("Zone | Priorität | Bereich | Verlust | Diagnose | Handlung")
        for i, (start, end, total_loss, spd, brk, thr, cause, advice) in enumerate(losses[:5], 1):
            prio = "HOCH" if total_loss >= 0.35 else ("MITTEL" if total_loss >= 0.18 else "NIEDRIG")
            sec = self.sector_name_for_m(start)  # 0.2.9: offizieller Sektor der Zone
            sec_txt = f" ({sec})" if sec else ""
            lines.append(
                f"Zone {i} | {prio} | {start}-{end} m{sec_txt} | {total_loss:+.3f} s | "
                f"{cause}; Speed {spd:+.1f} km/h, Brake {brk:+.3f}, Gas {thr:+.3f} | {advice}"
            )
        # One concise driver summary.
        main = losses[0]
        sec = self.sector_name_for_m(main[0])  # 0.2.9: offizieller Sektor der Hauptzone
        sec_txt = f" ({sec})" if sec else ""
        lines.append("")
        lines.append("Kurzfazit:")
        lines.append(
            f"Der größte kumulierte Verlust liegt in Zone 1 bei {main[0]}-{main[1]} m{sec_txt} ({main[2]:+.3f} s). "
            f"Hauptthema: {main[6]}. Nächster Run: nur diesen Bereich bewusst sauberer fahren."
        )
        lines.append("")
        lines.append("Live-Coaching-Vorbereitung:")
        lines.append("Diese Hinweise sind bewusst kurz formuliert, damit sie später als Sprachausgabe genutzt werden können.")
        return lines

    def limit_coach_assessment(self):
        """0.4.5.2: Simple Fahr-Limit-Coach.
        Labels deliberately stay human-readable and conservative:
        konservativ / sauber / am Limit / überfahren.
        This is not AI yet; it is rule-based context for the later KI-Coach.
        """
        if not self.samples:
            return "keine Daten", 0, ["Noch keine Samples. Für Limit-Coaching bitte eine saubere Session aufzeichnen."]
        reasons = []
        score = 0
        rows = self.input_coach_rows()
        if rows:
            avg_coast = sum(r["coast_pct"] for r in rows) / len(rows)
            avg_overlap = sum(r["overlap_pct"] for r in rows) / len(rows)
            total_release = sum(r["brake_release_spikes"] for r in rows)
            total_throttle = sum(r["throttle_spikes"] for r in rows)
            if avg_coast > 16:
                score -= 2; reasons.append(f"viel Rollenphase ({avg_coast:.1f}%) → eher konservativ/passiv")
            elif avg_coast > 10:
                score -= 1; reasons.append(f"etwas viel Rollenphase ({avg_coast:.1f}%)")
            if total_release > max(8, len(rows) * 4):
                score += 2; reasons.append(f"viele abrupte Bremslöse-Sprünge ({total_release}) → Auto wird wahrscheinlich überfahren")
            elif total_release > max(4, len(rows) * 2):
                score += 1; reasons.append(f"Bremslösung teilweise unruhig ({total_release})")
            if total_throttle > max(8, len(rows) * 4):
                score += 2; reasons.append(f"viele Gas-Sprünge ({total_throttle}) → Traktion/Balance am Limit")
            elif total_throttle > max(4, len(rows) * 2):
                score += 1; reasons.append(f"Gasaufbau teilweise ruppig ({total_throttle})")
            if avg_overlap > 6:
                score += 1; reasons.append(f"Gas/Bremse-Überlappung erhöht ({avg_overlap:.1f}%)")
        else:
            reasons.append("Noch keine gültigen sauberen Runden für Input-Bewertung.")

        zones = self.grouped_problem_zones() if self.segment_deltas else []
        if zones:
            main = zones[0]
            if main[2] >= 0.60:
                score += 2; reasons.append(f"großer Zeitverlust in Zone {main[0]}-{main[1]} m ({main[2]:+.3f}s)")
            elif main[2] >= 0.25:
                score += 1; reasons.append(f"relevanter Zeitverlust in Zone {main[0]}-{main[1]} m ({main[2]:+.3f}s)")
            # low speed delta with higher brake is often over-slowing, not true limit.
            if main[3] < -8 and main[4] > 0.08:
                score -= 1; reasons.append("Referenzvergleich deutet eher auf zu viel/zu lange Bremse als echtes Limit hin")
        elif self.reference_lap or self.external_reference:
            reasons.append("Referenz vorhanden, aber keine klare Problemzone erkannt.")

        if self.samples:
            flat_status = [self.flatspot_report_for_prefix(p) for p in ("tire_fl", "tire_fr", "tire_rl", "tire_rr")]
            if any("FLAT" in x or "REIFEN" in x or "LOCK!" in x or "ABS!" in x for x in flat_status):
                score += 2; reasons.append("Reifen-/Bremsstatus kritisch: " + ", ".join(flat_status))
            stats = self.tire_stats_summary() if self.samples else {}
            if stats:
                avg_temp = sum(v.get("temp_avg", 0.0) for v in stats.values()) / 4.0
                if avg_temp > 105:
                    score += 1; reasons.append(f"Reifen sehr warm ({avg_temp:.1f} °C) → Überfahren/Schonung prüfen")
                elif 70 <= avg_temp <= 100:
                    reasons.append(f"Reifenfenster wirkt brauchbar ({avg_temp:.1f} °C)")
                elif avg_temp and avg_temp < 60:
                    reasons.append(f"Reifen kalt ({avg_temp:.1f} °C) → Limit-Bewertung vorsichtig interpretieren")

        if score <= -2:
            level = "konservativ"
        elif score <= 1:
            level = "sauber"
        elif score <= 3:
            level = "am Limit"
        else:
            level = "überfahren"
        return level, score, reasons

    def limit_coach_report_lines(self, summary_only: bool = False) -> List[str]:
        level, score, reasons = self.limit_coach_assessment()
        lines = ["", "Fahr-Limit-Coach 0.4.5.4:"]
        lines.append(f"Limit-Level: {level} | Score {score:+d}")
        if level == "keine Daten":
            lines.append("Noch keine Daten. Für sinnvolle Bewertung mindestens 3–5 saubere Runden oder eine Referenzrunde nutzen.")
            return lines
        if level == "konservativ":
            lines.append("Kurzdiagnose: Du lässt wahrscheinlich noch Zeit liegen, ohne das Auto wirklich ans Limit zu bringen.")
            lines.append("Nächster Run: eine Kurve wählen, Rollenphase reduzieren und früher kontrolliert ans Gas, nicht einfach später bremsen.")
        elif level == "sauber":
            lines.append("Kurzdiagnose: Fahrweise wirkt kontrolliert. Nächster Schritt ist gezielter Vergleich einzelner Problemzonen.")
            lines.append("Nächster Run: gleiche Linie und gleiche Inputs reproduzieren, dann nur eine Zone bewusst optimieren.")
        elif level == "am Limit":
            lines.append("Kurzdiagnose: Du bist nahe am Limit, aber einzelne Inputs/Zonen kosten Stabilität oder Zeit.")
            lines.append("Nächster Run: nicht mehr Attacke, sondern Bremse lösen/Gasaufbau ruhiger machen und Exit stabilisieren.")
        else:
            lines.append("Kurzdiagnose: Du überfährst wahrscheinlich Auto/Reifen oder erzeugst zu viel Input-Unruhe.")
            lines.append("Nächster Run: 2 Runden bewusst 95% fahren, frühere Bremsruhe, weicheres Gas, keine zusätzlichen Lenkkorrekturen erzwingen.")
        if not summary_only:
            lines.append("")
            lines.append("Warum:")
            for r in reasons[:10]:
                lines.append(f"- {r}")
            lines.append("")
            lines.append("Hinweis: 0.4.5.2 ist regelbasiert. Die spätere KI-Version soll Report, Telemetrie und Settings-Screenshots gemeinsam auswerten.")
        return lines

    def update_heatmap(self):
        if not hasattr(self, 'heatmap'):
            return
        ref_samples = self.external_reference_samples() if self.external_reference else (self.samples_for_reference_lap() if self.reference_lap else [])
        cmp_samples = self.samples_for_lap(self.compare_lap.lap_number) if self.compare_lap else []
        zones = self.grouped_problem_zones() if self.segment_deltas else []
        if ref_samples and cmp_samples and self.segment_deltas:
            self.heatmap.set_heatmap(self.samples, ref_samples, cmp_samples, self.segment_deltas, zones)
            self.heatmap.set_sector_info(self.official_sector_bounds())  # 0.2.9
            total = sum(d.delta_s for d in self.segment_deltas)
            zeroish = abs(total) < 0.001 and not zones
            self.heatmap_note.setText(
                f"{self.reference_display_label()} vs Vergleich Lap {self.compare_lap.lap_number} | "
                f"Delta gesamt {total:+.3f} s | Coach-Zonen: {len(zones)}"
                + (" | Hinweis: identische/neue Auto-Referenz, daher keine roten Zonen." if zeroish else "")
            )
        else:
            base = cmp_samples or ref_samples or self.samples
            self.heatmap.set_samples(base)
            self.heatmap.set_sector_info(self.official_sector_bounds())  # 0.2.9
            reason = "Noch keine Heatmap möglich: Referenz und gültige Vergleichsrunde nötig."
            if ref_samples and not cmp_samples:
                reason = "Referenz vorhanden, aber noch keine gültige Vergleichsrunde für Heatmap."
            elif cmp_samples and not ref_samples:
                reason = "Vergleichsrunde vorhanden, aber keine Referenzdaten für Heatmap."
            self.heatmap_note.setText(reason)

    def update_zone_table(self):
        if not hasattr(self, "zone_table"):
            return
        self.zone_table.setRowCount(0)
        zones = self.grouped_problem_zones() if self.segment_deltas else []
        for i, (start, end, total_loss, spd, brk, thr, cause, advice) in enumerate(zones[:8], 1):
            prio = "HOCH" if total_loss >= 0.35 else ("MITTEL" if total_loss >= 0.18 else "NIEDRIG")
            row = self.zone_table.rowCount(); self.zone_table.insertRow(row)
            sec = self.sector_name_for_m(start)  # 0.2.9: offizieller Sektor der Zone
            sec_txt = f" ({sec})" if sec else ""
            vals = [f"Zone {i}", f"{start}-{end} m{sec_txt}", f"{total_loss:+.3f} s", prio, cause, advice, f"{spd:+.1f} km/h"]
            for c, v in enumerate(vals):
                self.zone_table.setItem(row, c, QTableWidgetItem(str(v)))
        self.zone_table.resizeColumnsToContents()

    def update_coach_text(self):
        if not hasattr(self, 'coach_text'):
            return
        text = "\n".join(self.coach_report_lines())
        self.coach_text.setPlainText(text)
        if hasattr(self, "limit_coach_text"):
            self.limit_coach_text.setPlainText("\n".join(self.limit_coach_report_lines()))
        self.refresh_dashboard()

    def safe_save_report_to_path(self, path) -> bool:
        try:
            self.last_report_save_error = ""
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            text = self.build_report()
            if not text or len(text) < 50:
                self.last_report_save_error = "Reporttext ist leer oder zu kurz"
                self.log.append(f"Report speichern unplausibel leer: {path.resolve()}")
                return False
            path.write_text(text, encoding="utf-8")
            ok = path.exists() and path.stat().st_size > 50
            if ok:
                self.log.append(f"Report gespeichert: {path.resolve()}")
                self._remember_session(path)  # 0.2.13
            else:
                self.last_report_save_error = "Datei wurde nicht oder leer geschrieben"
                self.log.append(f"Report speichern unplausibel leer: {path.resolve()}")
            return ok
        except Exception as e:
            self.last_report_save_error = f"{type(e).__name__}: {e}"
            self.log.append(f"Report speichern FEHLER: {self.last_report_save_error}")
            return False

    def safe_save_csv_to_path(self, path) -> bool:
        try:
            self.last_csv_save_error = ""
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.write_csv(path)
            ok = path.exists() and path.stat().st_size > 50
            if ok:
                self.log.append(f"CSV gespeichert: {path.resolve()}")
            else:
                self.last_csv_save_error = "CSV wurde nicht oder leer geschrieben"
                self.log.append(f"CSV speichern unplausibel leer: {path.resolve()}")
            return ok
        except Exception as e:
            self.last_csv_save_error = f"{type(e).__name__}: {e}"
            self.log.append(f"CSV speichern FEHLER: {self.last_csv_save_error}")
            return False

    def autosave_exports(self):
        """0.2.30: liefert ein Ergebnis-Dict zurueck, damit der Stopp
        Klartext-Feedback geben kann (Statusleiste + Dialog mit Ordner-
        Oeffnen). Vorher stand 'gespeichert' in der Statusleiste, selbst
        wenn nichts geschrieben wurde - Marcel fand keinen Report."""
        result = {
            "skipped": None, "report_ok": False, "csv_ok": False,
            "report_path": None, "csv_path": None,
            "report_error": "", "csv_error": "",
            "samples": len(self.samples),
            "rejected": getattr(self, "rejected_sample_count", 0),
        }
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        if not self.samples:
            result["skipped"] = "keine Samples vorhanden"
            # 0.2.39: letzten Verbindungsfehler mit in die Diagnose aufnehmen
            _verr = getattr(self, "_live_err", None) or "kein Fehler protokolliert (Spiel lief evtl. erst nach dem Stopp?)"
            result["conn_error"] = _verr
            self.log.append(
                "Auto-Report/CSV übersprungen: keine Samples vorhanden "
                f"(verworfen wegen Fahrzeug-/Streckenwechsel oder Garage/Pit: {result['rejected']}). "
                f"Letzter Verbindungsfehler: {_verr}"
            )
            return result
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        rp = REPORT_DIR / f"r3e_live_recorder_{stamp}.txt"
        cp = CSV_DIR / f"r3e_live_recorder_samples_{stamp}.csv"
        result["report_ok"] = self.safe_save_report_to_path(rp)
        result["csv_ok"] = self.safe_save_csv_to_path(cp)
        result["report_path"] = str(rp.resolve())
        result["csv_path"] = str(cp.resolve())
        result["report_error"] = getattr(self, "last_report_save_error", "")
        result["csv_error"] = getattr(self, "last_csv_save_error", "")
        if result["report_ok"] and result["csv_ok"]:
            self.log.append(f"Auto-Save OK: Report + CSV gespeichert in {EXPORT_DIR.resolve()}")
        else:
            self.log.append(f"Auto-Save FEHLER: Report_ok={result['report_ok']}, CSV_ok={result['csv_ok']}. Bitte Logpfad prüfen: {EXPORT_DIR.resolve()}")
        return result

    def autosave_feedback(self, res: dict):
        """0.2.30: Klartext nach dem Stopp - Statusleiste UND Dialog mit
        'Ordner oeffnen'. Nur bei echtem Dialog-Start (nicht beim App-Schliessen)."""
        try:
            if not res:
                return
            if res.get("skipped"):
                self.status.setText(
                    f"Kein Report gespeichert: {res['skipped']} "
                    f"(Samples: {res['samples']}, verworfen: {res['rejected']}). Details im Log."
                )
                msg = (
                    "Es wurde KEIN Report gespeichert.\n\n"
                    f"Grund: {res['skipped']}\n"
                    f"Gesammelte Samples: {res['samples']}\n"
                    f"Verworfene Samples (Fahrzeugwechsel/Garage/Pit): {res['rejected']}\n\n"
                    "Haeufigste Ursachen:\n"
                    "- Aufzeichnung gestartet, aber danach nicht gefahren\n"
                    "- Aufzeichnung laenger laufen lassen, nachdem RaceRoom/Session beendet wurde\n"
                    "- Recording-Lock auf ein anderes Fahrzeug als das gefahrene\n\n"
                    "Letzter Verbindungsfehler von RaceRoom:\n"
                    f"{res.get('conn_error') or 'keiner protokolliert'}"
                )
            elif res.get("report_ok") and res.get("csv_ok"):
                self.status.setText(f"Report gespeichert: {res['report_path']}")
                msg = (
                    "Report + CSV wurden gespeichert:\n\n"
                    f"Report: {res['report_path']}\n"
                    f"CSV: {res['csv_path']}\n\n"
                    f"Samples: {res['samples']}"
                )
            else:
                rerr = res.get("report_error") or "unbekannter Fehler"
                cerr = res.get("csv_error") or "unbekannter Fehler"
                self.status.setText(f"Auto-Save FEHLER (Report/CSV). Details im Log.")
                msg = (
                    "Beim Speichern ist ein Fehler aufgetreten:\n\n"
                    f"Report: {'OK - ' + str(res.get('report_path')) if res.get('report_ok') else 'FEHLER - ' + rerr}\n"
                    f"CSV: {'OK - ' + str(res.get('csv_path')) if res.get('csv_ok') else 'FEHLER - ' + cerr}\n\n"
                    f"Ziel-Ordner: {REPORT_DIR.resolve()}"
                )
            if getattr(self, "_app_closing", False):
                return  # 0.2.29: beim App-Schliessen keinen Dialog blockieren
            box = QMessageBox(self)
            box.setWindowTitle("Aufzeichnung gestoppt")
            box.setText(msg)
            btn_open = box.addButton("Ordner öffnen", QMessageBox.ActionRole)
            box.addButton("OK", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() is btn_open:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(REPORT_DIR.resolve())))
        except Exception as e:
            try:
                self.log.append(f"Auto-Save-Feedback fehlgeschlagen: {type(e).__name__}: {e}")
            except Exception:
                pass


    def tire_grip_hint(self, avg_temp: float, wear_pct: float, pressure_kpa: float, spread: float) -> str:
        # 4.3: berechnete Schätzung. RaceRoom liefert hier keinen direkten Grip-%-Wert.
        score = 100.0
        notes = []
        if avg_temp <= 0:
            return "keine Daten"
        if avg_temp < 65:
            score -= 28; notes.append("kalt")
        elif avg_temp > 105:
            score -= 25; notes.append("heiß")
        elif 75 <= avg_temp <= 95:
            notes.append("Temp gut")
        else:
            score -= 8; notes.append("Temp ok")
        # tire_wear wirkt in RaceRoom wie Restzustand: hoch = gut/frisch, niedrig = stärker verbraucht.
        if wear_pct <= 0:
            pass
        elif wear_pct < 55:
            score -= 25; notes.append("Wear hoch")
        elif wear_pct < 75:
            score -= 12; notes.append("Wear mittel")
        else:
            notes.append("Wear gut")
        if pressure_kpa > 0:
            if pressure_kpa < 145:
                score -= 10; notes.append("Druck niedrig")
            elif pressure_kpa > 190:
                score -= 10; notes.append("Druck hoch")
        if abs(spread) > 12:
            score -= 10; notes.append("I/O Spread")
        score = max(0, min(100, score))
        level = "Grip perfekt" if score >= 92 else ("Grip hoch" if score >= 80 else ("Grip mittel" if score >= 60 else "Grip niedrig"))
        return f"{level} · " + ", ".join(notes)

    def tire_setup_hint(self, out_t: float, mid_t: float, in_t: float, pressure_kpa: float, wear_pct: float) -> str:
        if max(out_t, mid_t, in_t, pressure_kpa) <= 0:
            return "keine Daten"
        hints = []
        spread = in_t - out_t
        avg_t = (out_t + mid_t + in_t) / 3.0 if (out_t or mid_t or in_t) else 0.0
        if avg_t < 65:
            hints.append("Reifen kalt")
        elif avg_t > 105:
            hints.append("Reifen heiß")
        if abs(spread) >= 12:
            if spread > 0:
                hints.append("innen wärmer: Sturz/Belastung prüfen")
            else:
                hints.append("außen wärmer: Untersteuer-/Sturzthema prüfen")
        if mid_t > max(out_t, in_t) + 6:
            hints.append("Mitte wärmer: Druck eher hoch")
        elif mid_t + 6 < min(out_t, in_t):
            hints.append("Mitte kühler: Druck eher niedrig")
        if pressure_kpa and pressure_kpa < 145:
            hints.append("Druck niedrig")
        elif pressure_kpa > 190:
            hints.append("Druck hoch")
        if 0 < wear_pct < 60:
            hints.append("Wear kritisch")
        return ", ".join(hints) if hints else "ok"

    def tire_stats_summary(self):
        """Aggregate tire stats for report/setup-coach. Returns dict keyed by FL/FR/RL/RR display names."""
        specs = [("VL", "tire_fl"), ("VR", "tire_fr"), ("HL", "tire_rl"), ("HR", "tire_rr")]
        def finite(vals):
            out = []
            for v in vals:
                try:
                    x = float(v)
                    if math.isfinite(x):
                        out.append(x)
                except Exception:
                    pass
            return out
        def avg(vals):
            vals = finite(vals)
            return sum(vals) / len(vals) if vals else 0.0
        data = {}
        for name, prefix in specs:
            p = [x for x in finite([getattr(s, f"{prefix}_pressure_kpa", 0.0) for s in self.samples]) if 60.0 <= x <= 350.0]
            out_t = [x for x in finite([getattr(s, f"{prefix}_temp_l_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            mid_t = [x for x in finite([getattr(s, f"{prefix}_temp_c_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            in_t = [x for x in finite([getattr(s, f"{prefix}_temp_r_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            carc = [x for x in finite([getattr(s, f"{prefix}_carcass_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            wear = [x for x in finite([getattr(s, f"{prefix}_wear_pct", 0.0) for s in self.samples]) if 0.0 < x <= 100.0]
            oa, ma, ia = avg(out_t), avg(mid_t), avg(in_t)
            pa, wa, ca = avg(p), avg(wear), avg(carc)
            temp_avg = (oa + ma + ia) / 3.0 if any([oa, ma, ia]) else 0.0
            spread = ia - oa
            data[name] = {
                "pressure": pa, "pressure_min": min(p or [0.0]), "pressure_max": max(p or [0.0]),
                "out": oa, "mid": ma, "in": ia, "temp_avg": temp_avg, "carcass": ca,
                "wear": wa, "spread": spread,
                "hint": self.tire_setup_hint(oa, ma, ia, pa, wa),
            }
        return data

    def tire_setup_coach_lines(self) -> List[str]:
        lines = ["Reifen-/Setup-Coach 4.4"]
        if not self.samples:
            lines.append("Noch keine Samples. Für echte Hinweise bitte Recording starten und 5–10 Runden fahren.")
            return lines
        stats = self.tire_stats_summary()
        if len(self.samples) < 300:
            lines.append("Hinweis: Datenbasis noch klein. Hinweise sind nur grob. Für Setup-Entscheidungen bitte 5–10 Runden am Stück fahren.")
        else:
            lines.append("Datenbasis: Stintdaten vorhanden. Hinweise aus Durchschnitt/Trend, nicht aus einer einzelnen Momentaufnahme.")

        # Global pressure and temperature balance.
        avg_press = sum(v["pressure"] for v in stats.values()) / 4.0 if stats else 0.0
        avg_temp = sum(v["temp_avg"] for v in stats.values()) / 4.0 if stats else 0.0
        lines.append("")
        lines.append(f"Gesamtbild: Druck Ø {avg_press/100.0:.2f} bar | Reifen-Temp Ø {avg_temp:.1f} °C")
        if avg_temp < 65:
            lines.append("Priorität 1: Reifen sind insgesamt kalt. Erst mit mehreren sauberen Push-Runden bewerten; falls sie kalt bleiben, Startdruck eher leicht reduzieren oder aggressiver aufwärmen.")
        elif avg_temp > 105:
            lines.append("Priorität 1: Reifen sind insgesamt heiß. Stint schonender fahren; falls dauerhaft heiß, Startdruck/Setup prüfen.")
        else:
            lines.append("Temperaturfenster: grundsätzlich brauchbar. Einzelne Reifen-Spreads sind wichtiger als der Gesamtwert.")
        if avg_press > 0:
            if avg_press < 1.45 * 100:
                lines.append("Druckbild: eher niedrig. Auf Stabilität beim Einlenken und Walken achten.")
            elif avg_press > 1.85 * 100:
                lines.append("Druckbild: eher hoch. Kontaktfläche könnte kleiner werden; Mitte-Temperaturen beobachten.")
            else:
                lines.append("Druckbild: plausibel für aktuellen Teststand. Entscheidend ist der Verlauf über den Stint.")

        lines.append("")
        lines.append("Pro Reifen:")
        _ch = self.telemetry_channels_active()
        for name in ["VL", "VR", "HL", "HR"]:
            v = stats.get(name, {})
            if not v:
                continue
            wear_txt = f"Rest {v['wear']:.0f}%" if _ch["wear"] else "Wear im Spiel deaktiviert"
            lines.append(f"{name}: {v['pressure']/100.0:.2f} bar | A/M/I {v['out']:.0f}/{v['mid']:.0f}/{v['in']:.0f} °C | {wear_txt} | {v['hint']}")
            sp = v.get("spread", 0.0)
            mid = v.get("mid", 0.0)
            hot_side = "innen" if sp > 8 else ("außen" if sp < -8 else "gleichmäßig")
            if hot_side == "innen":
                lines.append(f"  → Innen deutlich wärmer: Sturz/Belastung beobachten. Wenn das über viele Runden bleibt, etwas weniger negativen Sturz testen.")
            elif hot_side == "außen":
                lines.append(f"  → Außen deutlich wärmer: Reifen wird außen belastet. Einlenken/Untersteuern prüfen; ggf. Sturz/ARB/Balancing beobachten.")
            if mid > max(v.get("out", 0.0), v.get("in", 0.0)) + 6:
                lines.append("  → Mitte wärmer als Schultern: Druck tendenziell zu hoch für diesen Reifen.")
            elif mid + 6 < min(v.get("out", 0.0), v.get("in", 0.0)):
                lines.append("  → Mitte kühler als Schultern: Druck tendenziell zu niedrig für diesen Reifen.")

        # Axle balance.
        front_temp = (stats["VL"]["temp_avg"] + stats["VR"]["temp_avg"]) / 2.0
        rear_temp = (stats["HL"]["temp_avg"] + stats["HR"]["temp_avg"]) / 2.0
        front_wear = (stats["VL"]["wear"] + stats["VR"]["wear"]) / 2.0
        rear_wear = (stats["HL"]["wear"] + stats["HR"]["wear"]) / 2.0
        lines.append("")
        lines.append("Balance-Hinweis:")
        if front_temp - rear_temp > 8 or rear_wear - front_wear > 4:
            lines.append("Vorderachse stärker belastet: mögliches Untersteuern / zu viel Lenkwinkel / Front überfahren. Fahrstil und Front-Setup beobachten.")
        elif rear_temp - front_temp > 8 or front_wear - rear_wear > 4:
            lines.append("Hinterachse stärker belastet: mögliches Übersteuern / Traktionsthema. Gasannahme und Heckstabilität beobachten.")
        else:
            lines.append("Vorder-/Hinterachse wirken relativ ausgeglichen.")

        lines.append("")
        lines.append("Nächster Test: 8–10 Runden mit gleichem Fahrstil fahren. Danach prüfen wir, ob der Druck im Zielbereich landet und welche Reifen zuerst abbauen.")
        lines.append("Hinweis: Die Setup-Hinweise sind konservativ. Bitte immer nur eine Setup-Änderung auf einmal testen.")
        return lines

    def flatspot_report_for_prefix(self, prefix: str) -> str:
        if not self.samples:
            return "keine Daten"
        driving = [s for s in self.samples if not self.is_non_driving_sample(s) and getattr(s, "speed_kmh", 0.0) > 10]
        flat_seen = any(bool(getattr(s, f"{prefix}_flat", False)) for s in driving)
        if flat_seen:
            return "REIFEN PLATT"
        # Nur Bremsphasen bewerten, damit normale Kurvenslides nicht als Bremsplatte erscheinen.
        brake_rows = [s for s in driving if getattr(s, "brake", 0.0) > 0.35 and getattr(s, "speed_kmh", 0.0) > 30]
        vals = [float(getattr(s, f"{prefix}_grip_fract", 0.0) or 0.0) for s in brake_rows]
        vals = [v for v in vals if math.isfinite(v)]
        if not vals:
            return "OK"
        max_v = max(vals)
        cnt_warn = sum(1 for v in vals if v >= 0.25)
        is_abs_car = any(bool(getattr(s, "abs_on", False)) for s in driving[:200])
        # 0.2.4: ABS-Schwellen gelockert (0.60/0.35 statt 0.45/0.25, Warnzähler 12/5 statt 8/3).
        if is_abs_car:
            if max_v >= 0.60 or cnt_warn >= 12:
                return f"ABS! max {max_v:.2f}"
            if max_v >= 0.35 or cnt_warn >= 5:
                return f"ABS max {max_v:.2f}"
            return "OK"
        if max_v >= 0.45 or cnt_warn >= 8:
            return f"LOCK! max {max_v:.2f}"
        if max_v >= 0.25 or cnt_warn >= 3:
            return f"LOCK max {max_v:.2f}"
        if max_v >= 0.12:
            return f"leicht max {max_v:.2f}"
        return "OK"

    def flatspot_event_log_lines(self) -> List[str]:
        # 0.4.5.6: Ursprungssuche wird NUR durch einen bestaetigten Flatspot (echter RaceRoom-tire_flatspot)
        # ausgeloest. Fuer jeden Flat wird im Vorlauf das staerkste Ursachensignal gesucht:
        #   GT3/ABS   -> groesstes Lenk-Reversal (Dreher/Slide), da ABS Geradeaus-Blockaden verhindert.
        #   Nicht-GT3 -> haerteste Bremsung mit staerkster Verzoegerung (Lockup).
        # grip_fract wird nicht mehr genutzt (in echten RaceRoom-Aufnahmen leer).
        lines = ["", "Flatspot-Event-Log 0.4.5.6:"]
        if not self.samples:
            lines.append("Keine Daten.")
            return lines
        specs = [("VL", "tire_fl"), ("VR", "tire_fr"), ("HL", "tire_rl"), ("HR", "tire_rr")]
        driving = [(i, s) for i, s in enumerate(self.samples)
                   if not self.is_non_driving_sample(s) and float(getattr(s, "speed_kmh", 0.0) or 0.0) > 10.0]
        if not driving:
            lines.append("Keine fahrenden Samples (nur Pit/Stand/Outlap).")
            return lines
        is_abs_car = any(bool(getattr(s, "abs_on", False)) for _, s in driving[:200])
        mode = "Dreher/Slide" if is_abs_car else "Brems-Lockup"
        lines.append(f"Fahrzeugklasse: {'ABS an' if is_abs_car else 'ABS aus/nicht vorhanden'} -> Ursprungssuche via {mode}.")

        def g(s, a, d=0.0):
            v = getattr(s, a, d)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return d
            return v if math.isfinite(v) else d

        # Bestaetigte Flatspots (tire_flatspot, steigende Flanke); Position p im driving-Array merken.
        flats = []
        for name, prefix in specs:
            prev = False
            for p, (i, s) in enumerate(driving):
                fl = bool(getattr(s, f"{prefix}_flat", False))
                if fl and not prev:
                    flats.append((p, name, int(g(s, "lap_number")), g(s, "lap_dist_m")))
                prev = fl

        if not flats:
            lines.append("")
            lines.append("Keine bestaetigten Flatspots (RaceRoom) in dieser Session.")
            lines.append(f"Hinweis: Ohne tire_flatspot-Ereignis gibt es keinen Flatspot zu verorten. Die {mode}-"
                         "Ursprungssuche wird nur bei bestaetigtem Flatspot ausgeloest.")
            return lines

        LOOKBACK_M = 900.0
        def lookback_slice(p, flat_lap):
            out = []; crossed = 0; lap_prev = flat_lap; travelled = 0.0; last_dist = None
            q = p
            while q >= 0:
                i, s = driving[q]
                lap = int(g(s, "lap_number")); dist = g(s, "lap_dist_m")
                if lap != lap_prev:
                    crossed += 1
                    if crossed > 1:
                        break
                    lap_prev = lap; last_dist = None
                if last_dist is not None:
                    travelled += abs(last_dist - dist)
                last_dist = dist
                out.append(s)
                if travelled > LOOKBACK_M:
                    break
                q -= 1
            out.reverse()
            return out

        def spin_origin(sl):
            # Groesstes Lenk-Reversal ueber ein Fenster der letzten ~35 Samples; echtes
            # Reversal verlangt beide Seiten (>=+0.12 und <=-0.12). Invalidierte Runde bevorzugt.
            best = None; win = []
            for s in sl:
                win.append(s)
                if len(win) > 35:
                    win.pop(0)
                steers = [g(w, "steering") for w in win]
                smax, smin = max(steers), min(steers)
                if not (smax >= 0.12 and smin <= -0.12):
                    continue
                swing = smax - smin
                inv = any(bool(getattr(w, "lap_invalidated", False)) for w in win)
                score = swing + (0.4 if inv else 0.0)
                if best is None or score > best[0]:
                    pk = max(win, key=lambda w: abs(g(w, "steering")))
                    best = (score, pk, swing, inv)
            return best

        def lockup_origin(sl):
            best = None; win = []
            for s in sl:
                win.append(s)
                if len(win) > 15:
                    win.pop(0)
                brake = g(s, "brake"); spd = g(s, "speed_kmh")
                if brake < 0.6 or spd < 50:
                    continue
                drop = max(g(w, "speed_kmh") for w in win) - spd
                if best is None or drop > best[0]:
                    best = (drop, s, brake)
            return best

        lines.append("")
        lines.append("Bestaetigte Flatspots (RaceRoom) & wahrscheinlicher Ursprung:")
        for p, name, lap, dist in sorted(flats, key=lambda e: e[0]):
            sl = lookback_slice(p, lap)
            vmax = max((g(x, "speed_kmh") for x in sl), default=0.0)
            vmin = min((g(x, "speed_kmh") for x in sl), default=0.0)
            maxb = max((g(x, "brake") for x in sl), default=0.0)
            lines.append(f"{name} platt ab Lap {lap}, {dist:.0f} m")
            if is_abs_car:
                org = spin_origin(sl)
                if org:
                    _, os_, swing, inv = org
                    lines.append(f"  -> Ursprung (Dreher/Slide): Lap {int(g(os_,'lap_number'))}, ~{g(os_,'lap_dist_m'):.0f} m | "
                                 f"Lenk-Swing {swing:.2f}{' | Runde invalidiert' if inv else ''} | Speed dort {g(os_,'speed_kmh'):.0f} km/h")
                    lines.append(f"     Kontext im Vorlauf: Bremse bis {maxb*100:.0f} % | Speed-Fenster {vmax:.0f}->{vmin:.0f} km/h")
                else:
                    lines.append("  -> kein klares Lenk-Reversal im Vorlauf (evtl. Kontakt/Randstein/Curbing).")
            else:
                org = lockup_origin(sl)
                if org:
                    drop, os_, brake = org
                    lines.append(f"  -> Ursprung (Lockup): Lap {int(g(os_,'lap_number'))}, ~{g(os_,'lap_dist_m'):.0f} m | "
                                 f"Bremse {brake*100:.0f} % | Verzoegerung -{drop:.0f} km/h | Speed dort {g(os_,'speed_kmh'):.0f} km/h")
                else:
                    lines.append("  -> kein klarer Lockup im Vorlauf gefunden.")

        lines.append("")
        lines.append(f"Summe: {len(flats)} bestaetigte(r) Flatspot(s). Ursprung ist eine Heuristik ohne Raddrehzahl-Sensor: "
                     "GT3/ABS ueber groesstes Lenk-Reversal (Dreher/Slide), Nicht-ABS ueber haerteste Bremsung mit staerkster Verzoegerung (Lockup).")
        return lines

    def tire_report_lines(self) -> List[str]:
        lines = ["", "Reifenanalyse 4.4:"]
        if not self.samples:
            lines.append("Keine Reifendaten vorhanden.")
            return lines
        specs = [("VL", "tire_fl"), ("VR", "tire_fr"), ("HL", "tire_rl"), ("HR", "tire_rr")]
        def avg(vals):
            vals = [float(v) for v in vals if math.isfinite(float(v))]
            return sum(vals)/len(vals) if vals else 0.0
        def finite(vals):
            return [float(v) for v in vals if math.isfinite(float(v))]
        lines.append("Reifen | Druck kPa avg/min/max | Druck bar avg | Temp außen/mitte/innen avg °C | Carcass avg °C | Wear/Rest avg % | Spread innen-außen | Flat/ABS | Hinweis")
        _ch = self.telemetry_channels_active()
        for name, prefix in specs:
            pressures = [x for x in finite([getattr(s, f"{prefix}_pressure_kpa", 0.0) for s in self.samples]) if 60.0 <= x <= 350.0]
            out_t = [x for x in finite([getattr(s, f"{prefix}_temp_l_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            mid_t = [x for x in finite([getattr(s, f"{prefix}_temp_c_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            in_t = [x for x in finite([getattr(s, f"{prefix}_temp_r_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            carc = [x for x in finite([getattr(s, f"{prefix}_carcass_c", 0.0) for s in self.samples]) if -20.0 <= x <= 180.0]
            wear = [x for x in finite([getattr(s, f"{prefix}_wear_pct", 0.0) for s in self.samples]) if 0.0 < x <= 100.0]
            p_avg = avg(pressures); p_min = min(pressures or [0.0]); p_max = max(pressures or [0.0])
            out_avg, mid_avg, in_avg = avg(out_t), avg(mid_t), avg(in_t)
            carc_avg, wear_avg = avg(carc), avg(wear)
            temp_avg = (out_avg + mid_avg + in_avg) / 3.0 if any([out_avg, mid_avg, in_avg]) else 0.0
            spread = in_avg - out_avg
            hint = self.tire_setup_hint(out_avg, mid_avg, in_avg, p_avg, wear_avg)
            flat_line = self.flatspot_report_for_prefix(prefix)
            carc_txt = f"{carc_avg:.1f}" if _ch["carcass"] else "— (Spiel aus)"
            wear_txt = f"{wear_avg:.1f}" if _ch["wear"] else "— (Spiel aus)"
            lines.append(f"{name} | {p_avg:.1f}/{p_min:.1f}/{p_max:.1f} | {p_avg/100.0:.2f} | {out_avg:.1f}/{mid_avg:.1f}/{in_avg:.1f} | {carc_txt} | {wear_txt} | {spread:+.1f} | {flat_line} | {hint}")
        lines.append("")
        lines.append("Stint-Trend Reifen:")
        n = len(self.samples)
        if n >= 40:
            k = max(10, n // 5)
            first = self.samples[:k]; last = self.samples[-k:]
            for name, prefix in specs:
                def a(block, field):
                    vals = [getattr(s, field, 0.0) for s in block]
                    vals = [float(v) for v in vals if math.isfinite(float(v))]
                    if "pressure_kpa" in field:
                        vals = [v for v in vals if 60.0 <= v <= 350.0]
                    elif "wear_pct" in field:
                        vals = [v for v in vals if 0.0 < v <= 100.0]
                    elif "temp" in field:
                        vals = [v for v in vals if -20.0 <= v <= 180.0]
                    return sum(vals)/len(vals) if vals else 0.0
                p0, p1 = a(first, f"{prefix}_pressure_kpa"), a(last, f"{prefix}_pressure_kpa")
                t0 = (a(first, f"{prefix}_temp_l_c") + a(first, f"{prefix}_temp_c_c") + a(first, f"{prefix}_temp_r_c")) / 3.0
                t1 = (a(last, f"{prefix}_temp_l_c") + a(last, f"{prefix}_temp_c_c") + a(last, f"{prefix}_temp_r_c")) / 3.0
                w0, w1 = a(first, f"{prefix}_wear_pct"), a(last, f"{prefix}_wear_pct")
                wear_trend = f"Wear/Rest {w0:.1f}→{w1:.1f} %" if _ch["wear"] else "Wear im Spiel deaktiviert"
                lines.append(f"{name}: Druck {p0:.1f}→{p1:.1f} kPa ({p0/100.0:.2f}→{p1/100.0:.2f} bar), Temp {t0:.1f}→{t1:.1f} °C, {wear_trend}")
        else:
            lines.append("Zu wenig Samples für Trend. Für Stint-Trend bitte mindestens 3–5 volle Runden aufzeichnen.")
        lines.append("Hinweis: Flat/ABS nutzt den echten Flatspot-Status des Spiels. Mit aktivem ABS = ABS-Stress, ohne ABS = LOCK/LOCK!-Risiko.")
        lines.append("Wear/Rest wird aktuell als Restzustand interpretiert: höher = besser/frischer.")
        _disabled = [k for k, on in _ch.items() if not on]
        if _disabled:
            lines.append("⚠️ Im Spiel deaktivierte Kanäle erkannt: " + ", ".join(_disabled) + ". Deren Werte sind Ruhe-Defaults, keine Messwerte; zugehörige Hinweise entfallen.")
        return lines

    def lap_report_lines(self) -> List[str]:
        if not self.lap_summaries:
            self.update_laps()
        lines = ["", "Clean-Lap-Analyse:"]
        
        ref_sel = "Importierte Referenz" if self.use_external_reference and self.external_reference else (self.manual_reference_lap or "Auto")
        lines.append(f"Auswahl: Referenz={ref_sel} | Vergleich={self.manual_compare_lap or 'Auto'}")
        official_best = self.sim_best_lap_from_scoring()
        if official_best > 0:
            lines.append(f"Offizielle Bestzeit aus Scoring: {fmt_lap_time(official_best)}")
        if self.reference_lap:
            label = "Session-Referenz" if self.use_external_reference and self.external_reference else "Referenzrunde"
            lines.append(f"{label}: Lap {self.reference_lap.lap_number} | Avg Speed {self.reference_lap.avg_speed:.1f} km/h | Fuel {self.reference_lap.fuel_used_l:.3f} L")
        else:
            lines.append("Referenzrunde: keine gültige komplette Runde erkannt")
        lines.append("Lap | Status | Grund | Samples | Coverage m | Dauer [m]:ss.000 | Max Speed | Avg Speed | Max Brake | Fuel Used")
        for l in self.lap_summaries:
            status = "REFERENZ" if self.reference_lap and l.lap_number == self.reference_lap.lap_number else ("gültig" if l.is_clean else ("ungültig (einbezogen)" if self.include_invalid_laps else "ausgeschlossen"))
            # 0.2.5: Unvollständige Runden zeigen keine Zeit mehr. Die offizielle Scoring-Zeit
            # (lap_time_previous_self) wird erst auf der Folgerunde gelesen und gehört dann zur
            # Vorrunde - für eine nicht komplette Runde ist sie irreführend (Lap 9 zeigte Lap 8).
            t_txt = fmt_lap_time(self.lap_time_for_report(l)) if l.is_complete else "—"
            lines.append(f"{l.lap_number} | {status} | {l.reason} | {l.samples}/{l.valid_samples} | {l.coverage_m:.1f} | {t_txt} | {l.max_speed:.1f} | {l.avg_speed:.1f} | {l.max_brake:.3f} | {l.fuel_used_l:.3f}")
        return lines

    def input_metrics_for_lap(self, lap: LapSummary) -> dict:
        """Gas-/Bremsverhalten einer Runde aus vorhandenen Samples ableiten.
        Die CSV zeichnet throttle/brake pro Sample bereits auf; diese Metriken machen daraus Coaching-Signale.
        """
        rows = [s for s in self.samples if s.lap_number == lap.lap_number and not self.is_non_driving_sample(s) and s.speed_kmh > 5]
        rows.sort(key=lambda s: s.timestamp)
        if len(rows) < 20:
            return {
                "lap": lap.lap_number, "max_brake": 0.0, "avg_brake": 0.0, "hard_brakes": 0,
                "brake_release_spikes": 0, "throttle_spikes": 0, "coast_pct": 0.0, "overlap_pct": 0.0,
                "hint": "zu wenig Daten"
            }
        driven = [s for s in rows if s.speed_kmh > 30]
        driven_n = max(1, len(driven))
        brake_vals = [s.brake for s in rows if s.brake > 0.05]
        max_brake = max([s.brake for s in rows] or [0.0])
        avg_brake = sum(brake_vals)/len(brake_vals) if brake_vals else 0.0
        hard_brakes = 0
        in_hard = False
        for s in rows:
            if s.brake > 0.75 and not in_hard:
                hard_brakes += 1; in_hard = True
            elif s.brake < 0.25:
                in_hard = False
        brake_release_spikes = 0
        throttle_spikes = 0
        prev = rows[0]
        for cur in rows[1:]:
            db = cur.brake - prev.brake
            dt = cur.throttle - prev.throttle
            # abrupte Bremslösung während relevanter Bremsphase
            if prev.brake > 0.30 and cur.brake > 0.05 and db < -0.16 and cur.speed_kmh > 40:
                brake_release_spikes += 1
            # 0.2.4: zu abrupte Gasannahme - Schwelle gelockert (0.40/0.30 statt 0.55/0.22):
            # die Nürburgring-Bestlap hatte viele kurze Gasstöße, ohne ruppig zu sein.
            if prev.throttle < 0.40 and dt > 0.30 and cur.speed_kmh > 35:
                throttle_spikes += 1
            prev = cur
        coast = sum(1 for s in driven if s.brake < 0.04 and s.throttle < 0.04)
        overlap = sum(1 for s in driven if s.brake > 0.08 and s.throttle > 0.08)
        coast_pct = 100.0 * coast / driven_n
        overlap_pct = 100.0 * overlap / driven_n
        hints = []
        if coast_pct > 14:
            hints.append("viel Rollen")
        elif coast_pct < 5:
            hints.append("direkte Inputs")
        if brake_release_spikes >= 5:
            hints.append("Bremse löst ruppig")
        elif brake_release_spikes <= 1 and max_brake > 0.5:
            hints.append("Bremslösung sauber")
        if throttle_spikes >= 8:
            hints.append("Gasannahme ruppig")
        elif throttle_spikes <= 3:
            hints.append("Gasannahme sauber")
        if overlap_pct > 4:
            hints.append("Gas/Bremse Überlappung")
        if hard_brakes >= 5 and max_brake > 0.90:
            hints.append("viele harte Bremsungen")
        if not hints:
            hints.append("unauffällig")
        return {
            "lap": lap.lap_number, "max_brake": max_brake, "avg_brake": avg_brake, "hard_brakes": hard_brakes,
            "brake_release_spikes": brake_release_spikes, "throttle_spikes": throttle_spikes,
            "coast_pct": coast_pct, "overlap_pct": overlap_pct, "hint": ", ".join(hints)
        }

    def input_coach_rows(self) -> List[dict]:
        if not self.lap_summaries:
            self.update_laps()
        rows = []
        for lap in self.lap_summaries:
            if lap.is_clean:
                rows.append(self.input_metrics_for_lap(lap))
        return rows

    def input_coach_report_lines(self, summary_only: bool = False) -> List[str]:
        rows = self.input_coach_rows()
        lines = ["", "Input-Coach 4.4.15 – Gas-/Bremsverhalten:"]
        lines.append("Throttle und Brake werden pro Sample in der CSV aufgezeichnet. Dieser Abschnitt verdichtet nur gültige, saubere Runden des gelockten Recording-Fahrzeugs.")
        if not rows:
            lines.append("Noch keine gültigen Runden für Input-Coaching erkannt.")
            return lines
        avg_coast = sum(r["coast_pct"] for r in rows)/len(rows)
        avg_overlap = sum(r["overlap_pct"] for r in rows)/len(rows)
        total_release = sum(r["brake_release_spikes"] for r in rows)
        total_throttle = sum(r["throttle_spikes"] for r in rows)
        lines.append(f"Gesamtbild: Rollen Ø {avg_coast:.1f}% | Gas/Bremse-Überlappung Ø {avg_overlap:.1f}% | Bremslöse-Sprünge {total_release} | Gas-Sprünge {total_throttle}")
        if avg_coast > 14:
            focus_line = "Coach-Fokus: Rollenphase reduzieren. Entweder sauber länger bremsen oder früher progressiv ans Gas."
        elif total_release > max(6, len(rows)*3):
            focus_line = "Coach-Fokus: Bremse ruhiger lösen. Nicht abrupt aufmachen, sondern Druck kontrolliert abbauen."
        elif total_throttle > max(6, len(rows)*3):
            focus_line = "Coach-Fokus: Gas progressiver aufbauen, besonders am Kurvenausgang."
        elif avg_overlap > 4:
            focus_line = "Coach-Fokus: Gas/Bremse-Überlappung prüfen. In GT3 mit ABS/TC nur bewusst nutzen, nicht dauerhaft mitschleppen."
        else:
            focus_line = "Coach-Fokus: Inputs wirken grundsätzlich sauber. Nächster Schritt: mit Referenzzonen koppeln."
        lines.append(focus_line)
        lines.append(self.hardware_input_hint(focus_line, rows))
        if summary_only:
            return lines
        lines.append("")
        lines.append("Lap | Max Bremse | Ø Bremse | Hartbremsungen | Bremslöse-Sprünge | Gas-Sprünge | Rollen % | Überlapp % | Hinweis")
        for r in rows:
            lines.append(f"{r['lap']} | {r['max_brake']:.3f} | {r['avg_brake']:.3f} | {r['hard_brakes']} | {r['brake_release_spikes']} | {r['throttle_spikes']} | {r['coast_pct']:.1f} | {r['overlap_pct']:.1f} | {r['hint']}")
        lines.append("")
        lines.append("Hinweis: Das ist Fahrinput-Coaching, keine Fahrzeugphysik-Wahrheit. Die Werte werden später mit Trackmap-/Problemzonen kombiniert.")
        return lines

    def update_input_coach(self):
        if not hasattr(self, "input_table"):
            return
        rows = self.input_coach_rows()
        self.input_table.setRowCount(0)
        for r in rows:
            row = self.input_table.rowCount(); self.input_table.insertRow(row)
            vals = [
                f"Lap {r['lap']}", f"{r['max_brake']:.3f}", f"{r['avg_brake']:.3f}", str(r['hard_brakes']),
                str(r['brake_release_spikes']), str(r['throttle_spikes']), f"{r['coast_pct']:.1f}", f"{r['overlap_pct']:.1f}", r['hint']
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter if c < 8 else Qt.AlignLeft | Qt.AlignVCenter)
                if c == 6 and r['coast_pct'] > 14:
                    item.setBackground(QColor(160, 100, 70, 150))
                elif c == 4 and r['brake_release_spikes'] >= 5:
                    item.setBackground(QColor(160, 100, 70, 150))
                elif c == 5 and r['throttle_spikes'] >= 8:
                    item.setBackground(QColor(160, 100, 70, 150))
                elif c == 7 and r['overlap_pct'] > 4:
                    item.setBackground(QColor(160, 100, 70, 150))
                self.input_table.setItem(row, c, item)
        self.input_table.resizeColumnsToContents()
        if hasattr(self, "input_coach_text"):
            self.input_coach_text.setPlainText("\n".join(self.input_coach_report_lines(summary_only=True)))

    def segment_report_lines(self) -> List[str]:
        lines = ["", "Interne Mini-Sektor-Analyse 50 m:"]
        lines.append("Hinweis: 50-m-Sektoren bleiben intern für Vergleich, Heatmap und Coach-Zonen. Der Report zeigt sie nicht mehr vollständig, damit die Auswertung lesbar bleibt.")
        lines.append("Für Rohdaten bitte die CSV verwenden. Sichtbar priorisiert werden Runden und Coach-Zonen.")
        return lines

    def select_fahrer_hardware_view(self):
        self.show_view("Fahrer & Hardware")

    def build_report(self) -> str:
        lines = [
            "PitBoss R3E – Dashboard/Referenz Report",
            f"Version: {APP_VERSION}",
            f"Zeitpunkt: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "Quelle: RaceRoom Shared Memory ($R3E, Struktur nach Sector3 r3e.h v3.5).",
            "SimHub wird nicht benötigt. Trackmap basiert auf pos_x/pos_z, Segmentierung auf lap_dist_m.",
            "Clean-Lap-Filter: Standphase/Pit/Outlap werden entfernt. Reifen-/Brems-/Schaden-Overlays, Referenzrunden, Input-Coach, Limit-Coach und Fahrer-/Hardwareprofile nutzen die RaceRoom-Telemetrie.",
            f"Gewähltes Setup: {self.selected_setup_label()}",
            f"Externe Referenz: {self.external_reference_label() if self.external_reference else 'nicht geladen'}",
            f"Auto-Bestlap-Export: {'AN' if self.auto_bestlap_export_enabled else 'AUS'} | Live-Puffer: {'AN' if self.auto_bestlap_live_mode else 'AUS'}" + (f" | Lap {self.auto_bestlap_lap_number} | {fmt_lap_time(self.auto_bestlap_time_s)} | {self.auto_bestlap_export_path}" if self.auto_bestlap_export_path else ""),
            "Hotkeys: " + hotkey_summary(self.hotkey_config) + " | Windows: nur Polling, keine parallelen App-Shortcuts",
            "Windows-Global-Hotkeys: " + "/".join(sorted(set(self.hotkey_config.values()))) + " werden zusätzlich per Tastatur-Polling erkannt. 4.2.6 entkoppelt App-Shortcut und Polling gegen Doppeltrigger.",
            f"Samples: {len(self.samples)}",
            ("Aufnahmetyp: Kurzaufnahme/Snapshot" if len(self.samples) < 100 else "Aufnahmetyp: Session/Recording"),
            ("Ansicht: Einfach (Dashboard/Live/Coach)" if getattr(self, "ui_simple", True) else "Ansicht: Experte (alle Ansichten)"),  # 0.2.10
            f"Recording-Fahrzeug-Lock: {self.sample_vehicle_label(self.recording_signature) if self.recording_signature else 'nicht aktiv/kein Lock'}",
            f"Verworfene Samples wegen Fahrzeug-/Klassenwechsel/ungültig: {self.rejected_sample_count}",
            "",
        ]
        # 0.2.8: Hardware-/Profil-Block aus dem Report entfernt - die Ansicht
        # "Fahrer & Hardware" ist aus der App gestrichen.
        if self.samples:
            last = self.samples[-1]
            lines += [
                "Letzter Sample:",
                self.sample_summary(last),
                "",
                "Min/Max:",
                f"Speed km/h: {min(s.speed_kmh for s in self.samples):.2f} – {max(s.speed_kmh for s in self.samples):.2f}",
                f"Fuel L: {min(s.fuel_l for s in self.samples):.3f} – {max(s.fuel_l for s in self.samples):.3f}",
                f"RPM: {min(s.rpm for s in self.samples):.0f} – {max(s.rpm for s in self.samples):.0f}",
                f"Throttle: {min(s.throttle for s in self.samples):.3f} – {max(s.throttle for s in self.samples):.3f}",
                f"Brake: {min(s.brake for s in self.samples):.3f} – {max(s.brake for s in self.samples):.3f}",
                f"Steering: {min(s.steering for s in self.samples):.5f} – {max(s.steering for s in self.samples):.5f}",
                f"Track m: {min(s.lap_dist_m for s in self.samples):.1f} – {max(s.lap_dist_m for s in self.samples):.1f}",
            ]
            lines += self.tire_report_lines()
            lines += self.flatspot_event_log_lines()
            lines += ["", "Reifen-/Setup-Coach 4.4:"] + self.tire_setup_coach_lines()[1:]
            lines += self.timing_probe_report_lines()
            lines += self.lap_report_lines()
            lines += self.input_coach_report_lines()
            lines += self.segment_report_lines()
            lines += self.lap_compare_report_lines()
            lines += self.heatmap_report_lines()
            lines += self.limit_coach_report_lines()
            lines += self.coach_report_lines()
            lines += [
                "",
                "Samples-Auszug:",
                "Hinweis: Report zeigt nur die ersten 10 und letzten 10 Samples. Die vollständigen Daten stehen in der CSV.",
            ]
            head = self.samples[:10]
            tail = self.samples[-10:] if len(self.samples) > 20 else []
            for smp in head:
                lines.append(self.sample_summary(smp))
            if tail:
                lines.append(f"... {len(self.samples) - 20} Samples ausgelassen ...")
                for smp in tail:
                    lines.append(self.sample_summary(smp))
        return "\n".join(lines)

    def save_report(self):
        # 4.2.4: Direkt speichern statt Dateidialog. Der Dialog war auf manchen Systemen unzuverlässig.
        default = REPORT_DIR / f"r3e_live_recorder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        if self.safe_save_report_to_path(default):
            self.status.setText(f"Report gespeichert: {default}")
        else:
            QMessageBox.warning(self, "Report speichern", f"Report konnte nicht gespeichert werden. Fehler: {self.last_report_save_error or 'unbekannt'}\nZiel: {default}")

    def write_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "timestamp", "game_version", "track", "player_name", "active_vehicles", "player_idx", "player_has_vehicle",
                "telem_id", "scoring_id", "vehicle_name", "vehicle_model", "vehicle_class", "speed_kmh", "gear", "rpm",
                "fuel_l", "fuel_capacity_l", "throttle", "brake", "steering", "pos_x", "pos_y", "pos_z",
                "lap_number", "completed_laps", "lap_dist_m", "current_lap_time", "last_lap_time", "best_lap_time",
                "lap_invalidated", "in_pits", "place",
                "tire_fl_pressure_kpa", "tire_fr_pressure_kpa", "tire_rl_pressure_kpa", "tire_rr_pressure_kpa",
                "tire_fl_temp_l_c", "tire_fl_temp_c_c", "tire_fl_temp_r_c",
                "tire_fr_temp_l_c", "tire_fr_temp_c_c", "tire_fr_temp_r_c",
                "tire_rl_temp_l_c", "tire_rl_temp_c_c", "tire_rl_temp_r_c",
                "tire_rr_temp_l_c", "tire_rr_temp_c_c", "tire_rr_temp_r_c",
                "tire_fl_carcass_c", "tire_fr_carcass_c", "tire_rl_carcass_c", "tire_rr_carcass_c",
                "tire_fl_wear_pct", "tire_fr_wear_pct", "tire_rl_wear_pct", "tire_rr_wear_pct",
                "tire_fl_pressure_bar", "tire_fr_pressure_bar", "tire_rl_pressure_bar", "tire_rr_pressure_bar",
                "tire_fl_flat", "tire_fr_flat", "tire_rl_flat", "tire_rr_flat",
                "tire_fl_grip_fract", "tire_fr_grip_fract", "tire_rl_grip_fract", "tire_rr_grip_fract",
                "tire_fl_flatspot_status", "tire_fr_flatspot_status", "tire_rl_flatspot_status", "tire_rr_flatspot_status",
                # 0.2.20: bisher nur live vorhandene Kanaele jetzt auch dauerhaft in der CSV
                "accel_lat_ms2", "accel_long_ms2",
                "g_force_lat", "g_force_long",
                "heading_deg", "velocity_lat_ms", "velocity_long_ms", "engine_torque_nm",
                "input_throttle", "input_brake", "input_clutch", "input_steering",
                "tc_on", "esp_on",
                "sector_index", "cur_sector1_s", "cur_sector2_s", "last_sector1_s", "last_sector2_s", "best_sector1_s", "best_sector2_s",
                "brake_fl_temp_raw", "brake_fr_temp_raw", "brake_rl_temp_raw", "brake_rr_temp_raw",
                "max_rpm", "virtual_energy", "ffb_torque", "steering_shaft_torque",
                "pit_state", "speed_limiter", "num_pitstops", "pit_window_status", "pit_elapsed_s", "pit_total_s",
                "gap_ahead_s", "gap_behind_s", "gap_leader_s",
                "abs_on",
                "dmg_engine_pct", "dmg_transmission_pct", "dmg_aero_pct", "dmg_suspension_pct",
                "tire_temp_cold_c", "tire_temp_opt_c", "tire_temp_hot_c",
                "rear_brake_bias", "brake_fl_pressure", "brake_fr_pressure", "brake_rl_pressure", "brake_rr_pressure",
                "tire_fl_slip_ms", "tire_fr_slip_ms", "tire_rl_slip_ms", "tire_rr_slip_ms",
                "session_type", "session_remaining_s", "session_current_et", "session_end_et",
                "game_phase", "yellow_flag_state", "player_flag",
                "track_length_m"
            ])
            for s in self.samples:
                w.writerow([
                    s.timestamp, s.game_version, s.track, s.player_name, s.active_vehicles, s.player_idx, int(s.player_has_vehicle),
                    s.telem_id, s.scoring_id, s.vehicle_name, s.vehicle_model, s.vehicle_class, f"{s.speed_kmh:.6f}", s.gear,
                    f"{s.rpm:.6f}", f"{s.fuel_l:.6f}", f"{s.fuel_capacity_l:.6f}", f"{s.throttle:.6f}",
                    f"{s.brake:.6f}", f"{s.steering:.6f}", f"{s.pos_x:.6f}", f"{s.pos_y:.6f}", f"{s.pos_z:.6f}",
                    s.lap_number, s.completed_laps, f"{s.lap_dist_m:.6f}", f"{s.current_lap_time:.6f}",
                    f"{s.last_lap_time:.6f}", f"{s.best_lap_time:.6f}", int(s.lap_invalidated), int(s.in_pits), s.place,
                    f"{s.tire_fl_pressure_kpa:.6f}", f"{s.tire_fr_pressure_kpa:.6f}", f"{s.tire_rl_pressure_kpa:.6f}", f"{s.tire_rr_pressure_kpa:.6f}",
                    f"{s.tire_fl_temp_l_c:.6f}", f"{s.tire_fl_temp_c_c:.6f}", f"{s.tire_fl_temp_r_c:.6f}",
                    f"{s.tire_fr_temp_l_c:.6f}", f"{s.tire_fr_temp_c_c:.6f}", f"{s.tire_fr_temp_r_c:.6f}",
                    f"{s.tire_rl_temp_l_c:.6f}", f"{s.tire_rl_temp_c_c:.6f}", f"{s.tire_rl_temp_r_c:.6f}",
                    f"{s.tire_rr_temp_l_c:.6f}", f"{s.tire_rr_temp_c_c:.6f}", f"{s.tire_rr_temp_r_c:.6f}",
                    f"{s.tire_fl_carcass_c:.6f}", f"{s.tire_fr_carcass_c:.6f}", f"{s.tire_rl_carcass_c:.6f}", f"{s.tire_rr_carcass_c:.6f}",
                    f"{s.tire_fl_wear_pct:.6f}", f"{s.tire_fr_wear_pct:.6f}", f"{s.tire_rl_wear_pct:.6f}", f"{s.tire_rr_wear_pct:.6f}",
                    f"{s.tire_fl_pressure_kpa/100.0:.6f}", f"{s.tire_fr_pressure_kpa/100.0:.6f}", f"{s.tire_rl_pressure_kpa/100.0:.6f}", f"{s.tire_rr_pressure_kpa/100.0:.6f}",
                    int(s.tire_fl_flat), int(s.tire_fr_flat), int(s.tire_rl_flat), int(s.tire_rr_flat),
                    f"{s.tire_fl_grip_fract:.6f}", f"{s.tire_fr_grip_fract:.6f}", f"{s.tire_rl_grip_fract:.6f}", f"{s.tire_rr_grip_fract:.6f}",
                    self.flatspot_status(s.tire_fl_flat, s.tire_fl_grip_fract, s.brake, s.speed_kmh),
                    self.flatspot_status(s.tire_fr_flat, s.tire_fr_grip_fract, s.brake, s.speed_kmh),
                    self.flatspot_status(s.tire_rl_flat, s.tire_rl_grip_fract, s.brake, s.speed_kmh),
                    self.flatspot_status(s.tire_rr_flat, s.tire_rr_grip_fract, s.brake, s.speed_kmh),
                    # 0.2.20: zusaetzliche Telemetrie-Kanaele, Reihenfolge exakt wie der Header
                    f"{s.accel_lat_ms2:.6f}", f"{s.accel_long_ms2:.6f}",
                    f"{s.g_force_lat:.6f}", f"{s.g_force_long:.6f}",
                    f"{s.heading_deg:.6f}", f"{s.velocity_lat_ms:.6f}", f"{s.velocity_long_ms:.6f}", f"{s.engine_torque_nm:.6f}",
                    f"{s.input_throttle:.6f}", f"{s.input_brake:.6f}", f"{s.input_clutch:.6f}", f"{s.input_steering:.6f}",
                    int(s.tc_on), int(s.esp_on),
                    s.sector_index, f"{s.cur_sector1_s:.6f}", f"{s.cur_sector2_s:.6f}", f"{s.last_sector1_s:.6f}", f"{s.last_sector2_s:.6f}", f"{s.best_sector1_s:.6f}", f"{s.best_sector2_s:.6f}",
                    f"{s.brake_fl_temp_raw:.6f}", f"{s.brake_fr_temp_raw:.6f}", f"{s.brake_rl_temp_raw:.6f}", f"{s.brake_rr_temp_raw:.6f}",
                    f"{s.max_rpm:.6f}", f"{s.virtual_energy:.6f}", f"{s.ffb_torque:.6f}", f"{s.steering_shaft_torque:.6f}",
                    s.pit_state, int(s.speed_limiter), s.num_pitstops, s.pit_window_status, f"{s.pit_elapsed_s:.6f}", f"{s.pit_total_s:.6f}",
                    f"{s.gap_ahead_s:.6f}", f"{s.gap_behind_s:.6f}", f"{s.gap_leader_s:.6f}",
                    int(s.abs_on),
                    f"{s.dmg_engine_pct:.6f}", f"{s.dmg_transmission_pct:.6f}", f"{s.dmg_aero_pct:.6f}", f"{s.dmg_suspension_pct:.6f}",
                    f"{s.tire_temp_cold_c:.6f}", f"{s.tire_temp_opt_c:.6f}", f"{s.tire_temp_hot_c:.6f}",
                    f"{s.rear_brake_bias:.6f}", f"{s.brake_fl_pressure:.6f}", f"{s.brake_fr_pressure:.6f}", f"{s.brake_rl_pressure:.6f}", f"{s.brake_rr_pressure:.6f}",
                    f"{s.tire_fl_slip_ms:.6f}", f"{s.tire_fr_slip_ms:.6f}", f"{s.tire_rl_slip_ms:.6f}", f"{s.tire_rr_slip_ms:.6f}",
                    s.session_type, f"{s.session_remaining_s:.6f}", f"{s.session_current_et:.6f}", f"{s.session_end_et:.6f}",
                    s.game_phase, s.yellow_flag_state, s.player_flag,
                    f"{s.track_length_m:.6f}"
                ])
    def save_csv(self):
        # 4.2.4: Direkt speichern statt Dateidialog, passend zum Auto-Save.
        default = CSV_DIR / f"r3e_live_recorder_samples_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        if self.safe_save_csv_to_path(default):
            self.status.setText(f"CSV gespeichert: {default}")
        else:
            QMessageBox.warning(self, "CSV speichern", f"CSV konnte nicht gespeichert werden. Siehe Log. Ziel: {default}")

    def closeEvent(self, event):  # 0.5.9.26: Live-Log beim Beenden sauber schliessen
        # 0.2.29: Laeuft noch eine Aufzeichnung, sie VOR dem eigentlichen
        # Schliessen stoppen - stop_recording() macht den kompletten Auto-Save
        # (Report + CSV + Referenz). Vorher geschah hier nichts: PitBoss mit
        # aktiver Aufnahme zugemacht = alle Samples verloren, kein Report.
        try:
            self._app_closing = True  # 0.2.30: Feedback-Dialog beim Schliessen unterdruecken
            if getattr(self, "recording", False):
                self.log.append("App wird geschlossen - laufende Aufnahme wird automatisch gestoppt und gespeichert.")
                self.stop_recording()
        except Exception as e:
            try:
                self.log.append(f"Auto-Save beim Schliessen fehlgeschlagen: {type(e).__name__}: {e}")
            except Exception:
                pass
        if getattr(self, "live_log_enabled", False):
            self.stop_live_log()
        # 0.2.19: Alle Overlay-Fenster schliessen. Die Overlays sind rahmenlose
        # Qt.Window-Fenster ohne Parent - sie hielten den Prozess am Leben und
        # das Reifen-Overlay blieb nach dem Beenden des Hauptfensters stehen
        # und liess sich nicht mehr schliessen.
        for w in self.all_overlay_windows():
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass
        # Sicherheitsnetz: auch Overlays auswaendiger Referenzen (Duplikate) schliessen
        try:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, OverlayWindow) or isinstance(w, TireOverlayWindow):
                    try:
                        w.close()
                        w.deleteLater()
                    except Exception:
                        pass
        except Exception:
            pass
        super().closeEvent(event)


def main():
    try:
        qInstallMessageHandler(qt_message_filter)
    except Exception:
        pass
    app = QApplication(sys.argv)
    # 0.4.5.2: Einige Windows/Qt-Kombinationen liefern einen Default-Font
    # mit pointSize -1. Das ist lauffähig, erzeugt aber eine CMD-Warnung.
    # Wir setzen deshalb nur bei ungültiger Größe einen sicheren Default.
    try:
        f = app.font()
        if f.pointSize() <= 0:
            f.setPointSize(10)
            app.setFont(f)
    except Exception:
        pass
    w = Main(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()











