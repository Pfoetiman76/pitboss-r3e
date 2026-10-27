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
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QIcon, QPixmap, QDesktopServices, QShortcut, QKeySequence, QFont, QFontMetricsF, QPainterPath

APP_VERSION = "0.2.21 Beta"
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
START_MODE_PATH = EXPORT_DIR / "start_mode.json"  # 0.2.7: gemerkter Start-Modus
UI_LAYOUT_PATH = EXPORT_DIR / "ui_layout.json"  # 0.2.10: Einfache Ansicht vs. Experte

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
    lap_rows = _re.findall(r"^\d+ \|\s*(?:REFERENZ|g\u00fcltig|ausgeschlossen)\s*\|", txt, _re.MULTILINE)
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
# 0.2.7: Start-Modus-Auswahl. Beim App-Start kann man sich auf einen Zweck
# festlegen (Aufzeichnung / Overlays / Coach / Alles). Der Modus waehlt nur die
# Ansicht und öffnet ggf. Overlay-Fenster - es wird nichts automatisch
# aufgezeichnet oder angesagt. "Merken" speichert die Wahl in start_mode.json.
# ---------------------------------------------------------------------------
START_MODES = [
    ("record", "Aufzeichnung", "Live-Ansicht mit Recorder - per Hotkey Start/Stop, Report/CSV automatisch."),
    ("overlays", "Overlays", "Reifen-Overlay + Monitor-Overlay sofort öffnen, Live-Ansicht im Hauptfenster."),
    ("coach", "Coach", "Coach-Ansicht öffnen und Monitor-Overlay zeigen (Ansagen bleiben AUS bis aktiviert)."),
    ("all", "Alles", "Volles Dashboard mit allen Ansichten - alles wie bisher."),
]


def load_start_mode():
    """0.2.7: (mode, remember) laden - ungültiges -> (None, False), dann fragt der Dialog."""
    try:
        raw = json.loads(START_MODE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None, False
    if not isinstance(raw, dict):
        return None, False
    mode = raw.get("mode")
    if mode not in {m[0] for m in START_MODES}:
        mode = None
    return mode, bool(raw.get("remember", False))


def save_start_mode(mode, remember):
    """0.2.7: Start-Modus in Dokumente\\PitBoss R3E\\start_mode.json speichern."""
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        START_MODE_PATH.write_text(json.dumps({"mode": mode, "remember": bool(remember)}, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def start_mode_label(mode):
    for mid, label, _desc in START_MODES:
        if mid == mode:
            return label
    return "Alles"


class StartModeDialog(QDialog):
    """0.2.7: Auswahl-Dialog beim Start: Aufzeichnung, Overlays, Coach oder Alles."""

    def __init__(self, parent=None, remember=False, mode=None):
        super().__init__(parent)
        self.mode = mode if mode in {m[0] for m in START_MODES} else None
        self.remember = bool(remember)
        self.setWindowTitle("PitBoss R3E – Start-Modus")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        head = QLabel("Womit willst du starten?")
        head.setStyleSheet("font-size: 15px; font-weight: 800;")
        layout.addWidget(head)
        sub = QLabel("Du kannst jederzeit oben über die Reiter/Navi wechseln - der Modus ist nur der bequeme Startpunkt.")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (mid, title, desc) in enumerate(START_MODES):
            btn = QPushButton(title + "\n" + desc)
            btn.setMinimumHeight(78)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(desc)
            if mid == self.mode:
                btn.setStyleSheet("font-weight: 800; border: 2px solid #e8212b;")
            btn.clicked.connect(lambda _c=False, m=mid: self._pick(m))
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)
        self.chk_remember = QCheckBox("Auswahl merken (beim Start nicht mehr fragen)")
        self.chk_remember.setChecked(bool(remember))
        layout.addWidget(self.chk_remember)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _pick(self, mode):
        self.mode = mode
        self.remember = self.chk_remember.isChecked()
        self.accept()

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
]
DEFAULT_HOTKEYS = {
    "tire_overlay": "F6", "auto_bestlap": "F7", "record": "F8", "snapshot": "F9",
    "overlay": "F10", "live_coach": "F11", "brake_coach": "F12",
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


class TelemetryGGWidget(QWidget):
    """0.2.21: G-G-Diagramm - Quer- vs. Laengs-G-Kraft, Farbe = Geschwindigkeit."""

    def __init__(self):
        super().__init__()
        self.points = []  # (g_lat, g_long, speed_kmh)
        self.setMinimumHeight(300)

    def set_points(self, pts):
        self.points = list(pts or [])
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(20, 20, 24))
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r = max(min(w, h) / 2.0 - 16.0, 40.0)
        scale = 2.75  # Rand des Diagramms in g
        # Raster: 1g/2g-Kreise + Achsen
        p.setPen(QPen(QColor(80, 80, 90), 1))
        for g in (1.0, 2.0):
            p.drawEllipse(QPointF(cx, cy), r * g / scale, r * g / scale)
        p.setPen(QPen(QColor(95, 95, 105), 1))
        p.drawLine(int(cx - r - 6), int(cy), int(cx + r + 6), int(cy))
        p.drawLine(int(cx), int(cy - r - 6), int(cx), int(cy + r + 6))
        p.setPen(QColor(150, 150, 160))
        p.drawText(QRectF(8, 6, 260, 18), Qt.AlignLeft, "G-G-Diagramm (quer = rechts/links, oben = Beschleunigung, unten = Bremsen)")
        for g in (1.0, 2.0):
            p.drawText(QRectF(cx + r * g / scale + 2, cy - 8, 40, 16), Qt.AlignLeft, str(int(g)) + "g")
        # Punkte: Farbe = Speed (blau langsam, gruen mittel, rot schnell)
        vmax = 300.0
        for pt in self.points:
            if pt[2] > vmax:
                vmax = pt[2]
        for gl, gt, spd in self.points:
            frac = max(0.0, min(1.0, spd / max(vmax, 60.0)))
            if frac < 0.33:
                col = QColor(70, 150, 235)
            elif frac < 0.66:
                col = QColor(90, 215, 120)
            else:
                col = QColor(235, 70, 60)
            p.setPen(QPen(col, 1))
            p.drawPoint(int(cx + (gl / scale) * r), int(cy - (gt / scale) * r))
        if not self.points:
            p.setPen(QColor(210, 210, 210))
            p.drawText(self.rect(), Qt.AlignCenter, "Noch keine G-Kraft-Daten (Aufzeichnung starten)")


class TelemetryTraceWidget(QWidget):
    """0.2.21: Spuren ueber Rundenmeter: G-quer, G-laengs, Lenkung, Gas/Bremse."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMinimumHeight(240)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(20, 20, 24))
        rows = self.rows
        if len(rows) < 2:
            p.setPen(QColor(210, 210, 210))
            p.drawText(self.rect(), Qt.AlignCenter, "Telemetrie-Spuren erscheinen mit aufgezeichneter Fahrt")
            return
        w, h = self.width(), self.height()
        left = 78
        dmax = 1.0
        for s in rows:
            d = float(getattr(s, "lap_dist_m", 0.0) or 0.0)
            if d > dmax:
                dmax = d
        if dmax <= 0:
            dmax = 1.0
        lanes = [
            ("G-quer", QColor(235, 70, 55), lambda s: max(-1.0, min(1.0, float(getattr(s, "g_force_lat", 0.0) or 0.0) / 2.5))),
            ("G-laengs", QColor(70, 190, 235), lambda s: max(-1.0, min(1.0, float(getattr(s, "g_force_long", 0.0) or 0.0) / 2.5))),
            ("Lenkung", QColor(235, 185, 60), lambda s: max(-1.0, min(1.0, float(s.steering)))),
            ("Gas/Bremse", QColor(90, 215, 120), lambda s: (float(s.throttle) if float(s.throttle) > 0.04 else -float(s.brake))),
        ]
        lane_h = h / float(len(lanes))
        for i, (label, col, fn) in enumerate(lanes):
            top = i * lane_h
            mid = top + lane_h / 2.0
            p.setPen(QPen(QColor(70, 70, 80), 1))
            p.drawLine(0, int(mid), w, int(mid))
            p.setPen(QColor(150, 150, 160))
            p.drawText(QRectF(6, top + 2, left - 8, 16), Qt.AlignLeft, label)
            p.setPen(QPen(col, 2))
            prev = None
            for s in rows:
                x = left + (float(getattr(s, "lap_dist_m", 0.0) or 0.0) / dmax) * (w - left - 6)
                y = mid - fn(s) * (lane_h / 2.0 - 6.0)
                if prev is not None:
                    if abs(x - prev[0]) > 160:  # Sprung ueber Start/Ziel: Linie unterbrechen
                        prev = None
                        continue
                    p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
                prev = (x, y)


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
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            lp = map_pt(last.pos_x, last.pos_z)
            painter.drawEllipse(lp, 5, 5)
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
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0.0, QColor(6, 6, 8, 200))
            g.setColorAt(1.0, QColor(6, 6, 8, 135))
