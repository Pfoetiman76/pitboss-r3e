# -*- coding: utf-8 -*-
"""
PitBoss R3E - VR-Overlay: Monitor-Spiegel (PBVR v3)
===================================================
Schreibt die VR-Tafeln in das Shared Memory, aus dem der OpenXR-API-Layer
im Spiel (XR_APILAYER_PitBossR3E_VR.dll, siehe vr_layer/) liest.

PBVR-Protokoll v3 (0.4.2.0: ein Quad JE OVERLAY, eigene Distanz + Kippung;
die DLL versteht weiterhin v1/v2 und zeigt ohne PitBoss ihr Testmuster):

  Header (Fixed, "<5I", 20 Bytes, Offset 0):
    [0] magic    = 0x52564250  ("PBVR" little-endian)
    [1] version  = 3
    [2] frame    = laufende Bildnummer; die DLL aktualisiert Texturen NUR
                   bei neuem Zaehler (Performance-Schutz, ~10 Hz)
    [3] count    = Anzahl belegter Slots
    [4] maxSlots = GROESSE der Slot-Tabelle (immer 16)

  Slot-Tabelle (16 x 48 Bytes = 768 Bytes, Offset 20), Eintrag "<5I7f":
    used   (u32)  = 1: Slot belegt
    w      (u32)  = Texturbreite
    h      (u32)  = Texturhoehe
    offset (u32)  = Byte-Offset der Pixel ab DATA_START
    pad    (u32)  = reserviert (0)
    quadW  (f32)  = Tafelbreite in Metern
    quadH  (f32)  = Tafelhoehe in Metern
    posX   (f32)  = Position im LOCAL-Raum
    posY   (f32)
    posZ   (f32)  = Abstand (negativ = vor dem Fahrer)
    pitch  (f32)  = Kippung vertikal in Radiant
    yaw    (f32)  = Kippung horizontal in Radiant

  Pixelbereich ab DATA_START = 20 + 768 = 788: je Slot w*h*4 Bytes
  B, G, R, A (vormultiplizertes Alpha, QImage.Format_ARGB32_Premultiplied).

Konzept "Monitor 1:1" (Marcels Ziel, 07.11.2026): Jedes gespiegelte Overlay
wird als EIGENE Tafel in der VR eingereicht - mit eigener Position auf dem
virtuellen Bildschirm, eigenem Abstand (vr_depth) und eigener Kippung
(vr_tilt). Overlays koennen komplett von der Anzeige getrennt werden:
"nur Monitor" (vr_hidden), "nur VR" (vr_vronly - Fenster am Monitor
unsichtbar, wird aber weiter gespiegelt).

Dieses Modul ist absichtlich frei von PySide6 (Protokoll, Geometrie und
Shared Memory sind pur und per Selftest pruefbar).
"""

import ctypes
import json
import struct
import sys

# ---------------------------------------------------------------------------
# Protokollkonstanten (muessen zum Layer passen)
# ---------------------------------------------------------------------------

MAGIC = 0x52564250          # "PBVR" little-endian
PROTOCOL_VERSION = 3        # PBVR v3 = ein Quad je Overlay
PROTOCOL_V2 = 2             # alte Gesamt-Leinwand (bleibt DLL-seitig lesbar)
PROTOCOL_V1 = 1             # alte Einzeltafel
HEADER_FMT = "<5I"          # magic, version, frame, count, maxSlots
HEADER_SIZE = struct.calcsize(HEADER_FMT)   # 20
SLOT_FMT = "<5I7f"          # used, w, h, offset, pad + 7 Pose-Floats
SLOT_SIZE = struct.calcsize(SLOT_FMT)       # 48
MAX_SLOTS = 16
DATA_START = HEADER_SIZE + MAX_SLOTS * SLOT_SIZE   # 788
MAPPING_NAME = "Local\\PitBossR3E_VR"       # sitzungsgleich mit dem Spielprozess
MAPPING_SIZE = 64 * 1024 * 1024            # 64 MB Deckel fuer alle Slot-Pixel

MAX_CANVAS = 4096            # Deckel gegen defekte Header
CAP_W, CAP_H = 4096, 4096    # Deckel = Layer-Obergrenze; 4K bleibt 1:1 scharf
REFRESH_S = 0.1              # max. 10 Spiegel-Bilder pro Sekunde
                            # (Telemetrie kommt ohnehin mit ~10 Hz; 20 Hz
                            # verdoppelten nur die grossen Kopien und
                            # verursachten Mikroruckler in der VR)

_PAGE_READWRITE = 0x04
_FILE_MAP_ALL_ACCESS = 0xF001F

# ---------------------------------------------------------------------------
# Konfiguration (vr_overlay.json)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "enabled": False,
    "show_frame": True,       # schraffierter Leinwand-Rahmen (Diagnose-Tafel)
    "vr_width_m": 1.6,        # Breite des VIRTUELLEN Bildschirms in Metern
    "vr_height_m": 0.35,      # Hoehe ueber dem Blickpunkt (Regler)
    "vr_dist_m": 1.2,         # Grund-Abstand vor dem Fahrer (Regler, positiv)
    "vr_opacity": 100,        # globale Deckkraft in Prozent (Regler)
    "vr_backdrop": 60,        # dunkler Hintergrund hinter jedem Overlay
                              # in Prozent (0 = aus); hebt die Schrift in
                              # der VR vom Rennbild ab (0.4.0.3)
    "vr_hidden": [],          # Overlay-Klassen "nur Monitor" (nicht spiegeln)
    "vr_vronly": [],          # Overlay-Klassen "nur VR" (am Monitor
                              # unsichtbar, werden aber gespiegelt)
    "vr_debug": False,        # 0.4.0.4: Diagnose - Magenta-Rahmen auf der
                              # Diagnose-Tafel + Spiegel-Fakten im Live-Log
    "vr_zoom": 1.0,           # 0.4.0.9: VR-Lesbarkeit - Overlays auf der
                              # Tafel vergroessern (1.0 = 1:1 wie Monitor)
    "vr_gain": 100,           # 0.4.0.10: Overlay-Hintergrund-Deckkraft
                              # in der VR in Prozent (0 = wie Monitor,
                              # 100 = voll deckend); nur das VR-Bild,
                              # die Schrift bleibt immer voll deckend
    "vr_depth": {},           # 0.4.1.1: per-Overlay-Abstand,
                              # Map {Klassenname: Faktor 0.5-2.0}
                              # (nah = groesser und naeher, fern = kleiner
                              # und weiter weg, um die Overlay-Mitte)
    "vr_tilt": {},            # 0.4.2.0: per-Overlay-Kippung,
                              # Map {Klassenname: [pitch_deg, yaw_deg]},
                              # Bereich +-60 Grad, Kippen um die Mitte
}


def load_config(path) -> dict:
    """Gespeicherte Konfiguration, gemischt mit den Standardwerten."""
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in data.items():
                if k in DEFAULTS:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


def save_config(path, updates: dict) -> dict:
    """Einzelne Werte ergaenzen/ueberschreiben und zurueckschreiben."""
    try:
        data = load_config(path)
        data.update(updates)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
    return load_config(path)

# ---------------------------------------------------------------------------
# Geometrie (bildschirmunabhaengig testbar)
# ---------------------------------------------------------------------------

def canvas_size(screen_w: int, screen_h: int):
    """Leinwandgroesse (Diagnose-Tafel) aus der Bildschirmgroesse."""
    sw, sh = max(1, int(screen_w)), max(1, int(screen_h))
    s = min(1.0, CAP_W / sw, CAP_H / sh)
    w = max(64, min(MAX_CANVAS, int(round(sw * s))))
    h = max(64, min(MAX_CANVAS, int(round(sh * s))))
    return (w, h, s)


def board_pose(cfg: dict, canvas_w: int, canvas_h: int):
    """Pose des VIRTUELLEN Bildschirms (fuer die Diagnose-Tafel):
    (quadW, quadH, posX, posY, posZ, pitch, yaw)."""
    qw = float(cfg.get("vr_width_m", DEFAULTS["vr_width_m"]))
    qw = min(20.0, max(0.1, qw))
    qh = qw * float(canvas_h) / max(1, float(canvas_w))
    hy = float(cfg.get("vr_height_m", DEFAULTS["vr_height_m"]))
    dist = abs(float(cfg.get("vr_dist_m", DEFAULTS["vr_dist_m"])))
    return (qw, qh, 0.0, min(10.0, max(-10.0, hy)), -min(10.0, max(0.1, dist)), 0.0, 0.0)


def overlay_pose(cfg: dict, canvas_w: int, canvas_h: int,
                 screen_x: float, screen_y: float,
                 screen_w: float, screen_h: float):
    """Pose eines Overlays auf dem virtuellen Bildschirm.

    screen_x/screen_y = Mitte des Overlays in LEINWAND-Pixeln (bereits
    mit Zoom/Abstand skaliert), screen_w/screen_h = seine skalierte
    Groesse in Leinwand-Pixeln. Rueckgabe:
    (quadW, quadH, posX, posY, posZ, pitch_rad, yaw_rad).

    Abstand (vr_depth-Faktor df): df>1 schiebt das Overlay NAeher
    (kleineres |z|) und vergroessert es; df<1 weiter weg. Die Kippung
    kommt aus vr_tilt (Grad) und wird hier in Radiant uebersetzt.
    """
    boardW, boardH, _, posY0, posZ0, _, _ = board_pose(cfg, canvas_w, canvas_h)
    cw = max(1.0, float(canvas_w))
    ch = max(1.0, float(canvas_h))
    u = screen_x / cw            # 0..1 ueber den virtuellen Bildschirm
    v = screen_y / ch
    pos_x = (u - 0.5) * boardW
    pos_y = (0.5 - v) * boardH + posY0
    quad_w = boardW * max(1.0, screen_w) / cw
    # Tiefen-Faktor: 0.5..2.0 -> Abstand /df (nah) bzw. *1/df (fern)
    pos_z = posZ0  # Grundabstand; Anpassung durch df geschieht beim Aufrufer
    return (quad_w, 0.0, pos_x, pos_y, pos_z, 0.0, 0.0)


def tilt_from_config(cfg: dict, cls: str):
    """Kippung eines Overlays aus vr_tilt: (pitch_rad, yaw_rad)."""
    try:
        t = (cfg.get("vr_tilt", {}) or {}).get(cls) or (0.0, 0.0)
        p = max(-60.0, min(60.0, float(t[0])))
        y = max(-60.0, min(60.0, float(t[1])))
        import math
        return (math.radians(p), math.radians(y))
    except Exception:
        return (0.0, 0.0)


def depth_from_config(cfg: dict, cls: str):
    """Abstands-Faktor eines Overlays aus vr_depth (0.5..2.0)."""
    try:
        return max(0.5, min(2.0, float((cfg.get("vr_depth", {}) or {}).get(cls, 1.0))))
    except Exception:
        return 1.0


def mode_of(cfg: dict, cls: str):
    """Anzeige-Modus eines Overlays: 'both' | 'monitor' | 'vr'."""
    hidden = set(x for x in (cfg.get("vr_hidden", []) or []) if isinstance(x, str))
    vronly = set(x for x in (cfg.get("vr_vronly", []) or []) if isinstance(x, str))
    if cls in hidden:
        return "monitor"
    if cls in vronly:
        return "vr"
    return "both"


def hidden_classes(cfg: dict):
    """Namen der Overlay-Klassen, die nicht in die VR gespiegelt werden."""
    return set(x for x in (cfg.get("vr_hidden", []) or []) if isinstance(x, str))


def vronly_classes(cfg: dict):
    """Namen der Overlay-Klassen, die NUR in der VR sichtbar sind."""
    return set(x for x in (cfg.get("vr_vronly", []) or []) if isinstance(x, str))

# ---------------------------------------------------------------------------
# VRMirror: Shared Memory + Lebenszyklus
# ---------------------------------------------------------------------------

class VRMirror:
    """Haelt das PBVR-v3-Shared-Memory offen. publish_slots(slots) schreibt
    alle Overlay-Tafeln (Textur + Pose) und den Header mit neuem frame-
    Zaehler. Die DLL aktualisiert die Texturen nur bei neuem Zaehler -
    publish_slots() wird deshalb max. 10x pro Sekunde aufgerufen."""

    def __init__(self, cfg: dict = None):
        cfg = cfg or {}
        self.show_frame = bool(cfg.get("show_frame", True))
        self.opacity = min(1.0, max(0.05, float(cfg.get("vr_opacity", 100)) / 100.0))
        self._k32 = None
        self._hmap = None
        self._view = None
        self._frame = 0
        self._last = 0.0

    def update_pose(self, cfg: dict):
        """Regler-Aenderungen uebernehmen (Deckkraft fuer den QPainter)."""
        self.opacity = min(1.0, max(0.05, float((cfg or {}).get("vr_opacity", 100)) / 100.0))

    # -- Lebenszyklus -------------------------------------------------------

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            invalid = ctypes.c_void_p(-1).value  # INVALID_HANDLE_VALUE
            k32.CreateFileMappingW.restype = ctypes.c_void_p
            k32.CreateFileMappingW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_ulong, ctypes.c_ulong,
                                               ctypes.c_ulong, ctypes.c_wchar_p]
            h = k32.CreateFileMappingW(invalid, None, _PAGE_READWRITE, 0,
                                       MAPPING_SIZE, MAPPING_NAME)
            if not h:
                return False
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                          ctypes.c_ulong, ctypes.c_ulong,
                                          ctypes.c_size_t]
            v = k32.MapViewOfFile(h, _FILE_MAP_ALL_ACCESS, 0, 0, MAPPING_SIZE)
            if not v:
                k32.CloseHandle(ctypes.c_void_p(h))
                return False
            self._k32 = k32
            self._hmap = h
            self._view = v
            self._frame = 0
            return True
        except Exception:
            return False

    def stop(self):
        try:
            if self._view and self._k32:
                self._k32.UnmapViewOfFile(ctypes.c_void_p(self._view))
        except Exception:
            pass
        try:
            if self._hmap and self._k32:
                self._k32.CloseHandle(ctypes.c_void_p(self._hmap))
        except Exception:
            pass
        self._view = None
        self._hmap = None
        self._k32 = None

    # -- Bild-Pfad ----------------------------------------------------------

    def too_soon(self, now: float) -> bool:
        """True, wenn der letzte Spiegel noch keine REFRESH_S Sekunden alt ist."""
        return (now - self._last) < REFRESH_S

    @staticmethod
    def build_message(slots):
        """Header + Slot-Tabelle + alle Pixel als EINEN Bytes-Block bauen
        (rein, ohne Shared Memory - fuer den Selftest). slots: Liste von
        dicts mit w, h, pixels (bytes, Laenge w*h*4), quadW, quadH, posX,
        posY, posZ, pitch, yaw."""
        if len(slots) > MAX_SLOTS:
            raise ValueError("zu viele Slots")
        table = b""
        blob = b""
        for sl in slots:
            w = int(sl["w"])
            h = int(sl["h"])
            px = sl["pixels"]
            if w <= 0 or h <= 0 or w > MAX_CANVAS or h > MAX_CANVAS:
                raise ValueError("unzulaessige Slot-Groesse")
            if len(px) != w * h * 4:
                raise ValueError("Pixel-Laenge passt nicht zur Slot-Groesse")
            offset = DATA_START + len(blob)
            if offset + len(px) > MAPPING_SIZE:
                raise ValueError("Shared Memory zu klein")
            table += struct.pack(SLOT_FMT, 1, w, h, offset, 0,
                                 float(sl["quadW"]), float(sl["quadH"]),
                                 float(sl["posX"]), float(sl["posY"]),
                                 float(sl["posZ"]), float(sl["pitch"]),
                                 float(sl["yaw"]))
            blob += px
        table += struct.pack(SLOT_FMT, 0, 0, 0, 0, 0,
                             0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) * (MAX_SLOTS - len(slots))
        header = struct.pack(HEADER_FMT, MAGIC, PROTOCOL_VERSION, 0,
                             len(slots), MAX_SLOTS)
        return header + table + blob

    def publish_slots(self, slots, now: float = None) -> bool:
        """Alle Overlay-Tafeln ins Shared Memory schreiben (frame hochzaehlen).
        Rueckgabe False, wenn das Mapping fehlt oder die Daten unzulaessig
        sind; die alte VR wird dann mit dem letzten Stand weiter angezeigt."""
        if not self._view:
            return False
        try:
            msg = self.build_message(slots)
        except Exception:
            return False
        self._frame = (self._frame + 1) & 0xFFFFFFFF
        # frame-Zaehler im Header nachtragen (Platzhalter 0 oben)
        msg = (msg[:8]
               + struct.pack("<I", self._frame)
               + msg[12:])
        ctypes.memmove(self._view, msg, len(msg))
        if now is not None:
            self._last = now
        return True

# ---------------------------------------------------------------------------
# Selftest (python vr_overlay.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import math
    ok = True

    def check(name, cond, info=""):
        global ok
        passed = bool(cond)
        print(("PASS" if passed else "FAIL"), "-", name, info if not passed else "")
        ok = ok and passed

    check("Header-Layout: 5 x uint32 = 20 Bytes", HEADER_SIZE == 20, HEADER_SIZE)
    check("Slot-Layout: 5 x uint32 + 7 x float = 48 Bytes", SLOT_SIZE == 48, SLOT_SIZE)
    check("Datenbereich ab 788", DATA_START == 788, DATA_START)
    check("Protokoll v3", PROTOCOL_VERSION == 3)

    w, h, s = canvas_size(1920, 1080)
    check("1:1-Aufloesung bleibt unskaliert", (w, h, s) == (1920, 1080, 1.0), (w, h, s))
    w4, h4, s4 = canvas_size(3840, 2160)
    check("4K bleibt 1:1 (Schärfe, 0.4.0.2)", (w4, h4, s4) == (3840, 2160, 1.0), (w4, h4, s4))
    w5, h5, s5 = canvas_size(5120, 2880)
    check("5K wird auf 4096 gedeckelt", (w5, h5) == (4096, 2304) and 0.0 < s5 < 1.0, (w5, h5, s5))

    cfg = dict(DEFAULTS)
    qw, qh, px, py, pz, _, _ = board_pose(cfg, 1920, 1080)
    check("Board: Hoehe folgt Seitenverhaeltnis", abs(qh - 1.6 * 1080 / 1920) < 1e-9, qh)
    check("Board: Abstand negativ (vor dem Fahrer)", pz < 0, pz)

    ow, _, ox, oy, oz, _, _ = overlay_pose(cfg, 1920, 1080, 960.0, 540.0, 480.0, 270.0)
    check("Overlay-Mitte liegt auf Board-Mitte", abs(ox) < 1e-9 and abs(oy - py) < 1e-9, (ox, oy))
    ow2, _, ox2, _, _, _, _ = overlay_pose(cfg, 1920, 1080, 0.0, 0.0, 480.0, 270.0)
    check("Overlay links aussen: negative X-Position", ox2 < -0.1, ox2)
    check("Overlay-Groesse folgt Bildschirmanteil", abs(ow - 1.6 * 480 / 1920) < 1e-9, ow)

    p, y = tilt_from_config(dict(DEFAULTS, vr_tilt={"X": [30, -45]}), "X")
    check("Kippung Grad -> Radiant", abs(p - math.radians(30)) < 1e-9
          and abs(y - math.radians(-45)) < 1e-9, (p, y))
    p0, y0 = tilt_from_config(DEFAULTS, "Unbekannt")
    check("Kippung ohne Eintrag = 0", p0 == 0.0 and y0 == 0.0)
    check("Tilt-Bereich +-60 Grad geklemmt",
          tilt_from_config(dict(DEFAULTS, vr_tilt={"X": [90, 0]}), "X")[0] == math.radians(60))
    check("Depth-Standard 1.0", depth_from_config(DEFAULTS, "X") == 1.0)
    check("Depth-Bereich geklemmt",
          depth_from_config(dict(DEFAULTS, vr_depth={"X": 9.0}), "X") == 2.0)

    check("Modus: Standard beide", mode_of(DEFAULTS, "X") == "both")
    check("Modus: nur Monitor", mode_of(dict(DEFAULTS, vr_hidden=["X"]), "X") == "monitor")
    check("Modus: nur VR", mode_of(dict(DEFAULTS, vr_vronly=["X"]), "X") == "vr")

    slots = [{"w": 4, "h": 4, "pixels": bytes(4 * 4 * 4),
              "quadW": 0.4, "quadH": 0.3, "posX": 0.1, "posY": 0.0,
              "posZ": -1.0, "pitch": 0.0, "yaw": 0.5},
             {"w": 2, "h": 2, "pixels": bytes(2 * 2 * 4),
              "quadW": 0.2, "quadH": 0.15, "posX": -0.2, "posY": 0.1,
              "posZ": -1.4, "pitch": 0.2, "yaw": 0.0}]
    msg = VRMirror.build_message(slots)
    check("v3-Nachricht: Header + Tabelle + Pixel", len(msg) == DATA_START + 64 + 16, len(msg))
    vals = struct.unpack_from(HEADER_FMT, msg, 0)
    check("v3-Header: magic/version/count/maxSlots",
          vals[0] == MAGIC and vals[1] == 3 and vals[3] == 2 and vals[4] == MAX_SLOTS, vals)
    s1 = struct.unpack_from(SLOT_FMT, msg, HEADER_SIZE)
    s2 = struct.unpack_from(SLOT_FMT, msg, HEADER_SIZE + SLOT_SIZE)
    check("Slot 1: Groesse + Offset", s1[1] == 4 and s1[2] == 4 and s1[3] == DATA_START, s1[:4])
    check("Slot 2: Offset hinter Slot 1", s2[3] == DATA_START + 64, s2[:4])
    check("Slot-Pose durchgereicht", abs(s1[9] - (-1.0)) < 1e-6 and abs(s2[7] - (-0.2)) < 1e-6)
    empty = struct.unpack_from(SLOT_FMT, msg, HEADER_SIZE + 2 * SLOT_SIZE)
    check("Leere Slots: used=0", empty[0] == 0)
    try:
        VRMirror.build_message([{"w": 4, "h": 4, "pixels": bytes(63),
                                  "quadW": 0.1, "quadH": 0.1, "posX": 0, "posY": 0,
                                  "posZ": -1, "pitch": 0, "yaw": 0}])
        badlen = False
    except Exception:
        badlen = True
    check("Falsche Pixel-Laenge wird abgelehnt", badlen)

    m = VRMirror(DEFAULTS)
    check("VRMirror: publish ohne start() = False", m.publish_slots([]) is False)
    m._last = 100.0  # Basiszeit fuer den Drossel-Test
    check("VRMirror: zu frueh erkannt", m.too_soon(100.01) is True and m.too_soon(100.2) is False)

    print("SELTEST", "OK" if ok else "FEHLER")
    sys.exit(0 if ok else 1)
