# -*- coding: utf-8 -*-
"""
PitBoss R3E - VR-Overlay: Monitor-Spiegel (PBVR v2)
===================================================
Schreibt die VR-Leinwand in das Shared Memory, aus dem der OpenXR-API-Layer
im Spiel (XR_APILAYER_PitBossR3E_VR.dll, siehe vr_layer/) liest.

PBVR-Protokoll v2 (identisch zum Layer, siehe vr_layer/README.md):
  Header, Little-Endian ("5I5f", 40 Bytes):
    [0] magic   = 0x52564250  ("PBVR" little-endian)
    [1] version = 2           (1 = alte Einzeltafel, bleibt lesbar)
    [2] width   = Leinwandbreite  (z. B. 1920, gedeckelt bei 4096)
    [3] height  = Leinwandhoehe  (z. B. 1080)
    [4] frame   = laufende Bildnummer; der Layer aktualisiert die Textur
                  NUR bei neuem Zaehler (Performance-Schutz, ~20 Hz)
    [5] quadW   = Tafelbreite in Metern (VR)
    [6] quadH   = Tafelhoehe in Metern (aus dem Leinwand-Seitenverhaeltnis)
    [7] posX    = Position im LOCAL-Raum
    [8] posY    = Hoehe ueber dem Blickpunkt
    [9] posZ    = Abstand vor dem Fahrer (negativ)
  Danach: width * height Pixel, je 4 Bytes B, G, R, A. Der Monitor-Spiegel
  komponiert per QPainter auf ein QImage Format_ARGB32_Premultiplied - genau
  dieses Bytelayout (BGRA, vormultiplizert), wie es OpenXR-Composition-Layer
  beim Alpha-Blending erwarten (0.4.0.2).

Konzept "Monitor 1:1" (Marcels Ziel, 07.11.2026): Die Leinwand entspricht der
Bildschirmflaeche, jedes offene Desktop-Overlay wird an seiner Monitor-
Position gespiegelt. Fenster verschieben/skalieren/Deckkraft/zumachen am
Desktop wirkt sofort in der VR; der Layer zeigt ohne PitBoss sein Testmuster.

Dieses Modul ist absichtlich frei von PySide6 (Protokoll, Geometrie und
Shared Memory sind pur und per Selftest pruefbar).
"""

import ctypes
import json
import struct
import sys

# ---------------------------------------------------------------------------
# Protokoll-Konstanten (muessen zum Layer passen)
# ---------------------------------------------------------------------------

MAGIC = 0x52564250          # "PBVR" little-endian
PROTOCOL_VERSION = 2         # PBVR v2 = Monitor-Spiegel
PROTOCOL_V1 = 1              # alte Einzeltafel (bleibt lesbar)
HEADER_FMT = "<5I5f"         # magic, version, w, h, frame + 5 Pose-Floats
HEADER_SIZE = struct.calcsize(HEADER_FMT)   # 40
MAPPING_NAME = "Local\\PitBossR3E_VR"       # sitzungsgleich mit dem Spielprozess

MAX_CANVAS = 4096            # Deckel des Layers gegen defekte Header
CAP_W, CAP_H = 4096, 4096    # Deckel = Layer-Obergrenze; 4K bleibt 1:1 scharf
                            # (0.4.0.2: war 2560x1440 - Text wurde unscharf)
REFRESH_S = 0.1              # 0.4.1.1: max. 10 Spiegel-Bilder pro Sekunde
                            # (Telemetrie kommt ohnehin mit ~10 Hz; 20 Hz
                            # verdoppelten nur die ~20-MB-Kopien und
                            # verursachten Mikroruckler in der VR)

_PAGE_READWRITE = 0x04
_FILE_MAP_ALL_ACCESS = 0xF001F

# ---------------------------------------------------------------------------
# Konfiguration (vr_overlay.json)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "enabled": False,
    "show_frame": True,       # schraffierter Leinwand-Rahmen
    "vr_width_m": 1.6,        # Tafelbreite in der VR (Regler)
    "vr_height_m": 0.35,      # Hoehe ueber dem Blickpunkt (Regler)
    "vr_dist_m": 1.2,         # Abstand vor dem Fahrer (Regler, positiv)
    "vr_opacity": 100,        # globale Deckkraft in Prozent (Regler)
    "vr_backdrop": 60,        # dunkler Hintergrund hinter jedem Overlay
                              # in Prozent (0 = aus); hebt die Schrift in
                              # der VR vom Rennbild ab (0.4.0.3)
    "vr_hidden": [],          # Overlay-Klassen, die nicht gespiegelt werden
    "vr_debug": False,        # 0.4.0.4: Diagnose - Magenta-Rahmen auf der
                              # Leinwand + Spiegel-Fakten im Live-Log
    "vr_zoom": 1.0,           # 0.4.0.9: VR-Lesbarkeit - Overlays auf der
                              # Tafel vergroessern (1.0 = 1:1 wie Monitor)
    "vr_gain": 100,           # 0.4.0.10: Overlay-Hintergrund-Deckkraft
                              # in der VR in Prozent (0 = wie Monitor,
                              # 100 = voll deckend); nur das VR-Bild,
                              # die Schrift bleibt immer voll deckend
    "vr_depth": {},           # 0.4.1.1: per-Overlay-Abstand in der VR,
                              # Map {Overlay-Klassenname: Faktor 0.5-2.0}
                              # (nah = groesser, fern = kleiner, um die
                              # Overlay-Mitte skaliert)
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
    """Leinwandgroesse aus der Bildschirmgroesse.

    1:1-Spiegel: die Leinwand ist so gross wie der Bildschirm; erst ab
    4096 Pixel wird gedeckelt (Layer-Obergrenze). Rueckgabe: (w, h, scale)
    mit scale <= 1.0.
    """
    sw, sh = max(1, int(screen_w)), max(1, int(screen_h))
    s = min(1.0, CAP_W / sw, CAP_H / sh)
    w = max(64, min(MAX_CANVAS, int(round(sw * s))))
    h = max(64, min(MAX_CANVAS, int(round(sh * s))))
    return (w, h, s)


def pose_from_config(cfg: dict, w: int, h: int):
    """Pose-Floats fuer den Header: (quadW, quadH, posX, posY, posZ).

    quadH folgt aus dem Leinwand-Seitenverhaeltnis, damit der Spiegel nie
    verzerrt wird. Der Abstand wird positiv gespeichert und im Header als
    negatives z (vor dem Fahrer) geschrieben - der LOCAL-Raum zeigt -z nach
    vorn."""
    qw = float(cfg.get("vr_width_m", DEFAULTS["vr_width_m"]))
    qw = min(20.0, max(0.1, qw))
    qh = qw * float(h) / float(w)
    hy = float(cfg.get("vr_height_m", DEFAULTS["vr_height_m"]))
    dist = abs(float(cfg.get("vr_dist_m", DEFAULTS["vr_dist_m"])))
    return (qw, qh, 0.0, min(10.0, max(-10.0, hy)), -min(10.0, max(0.1, dist)))


def hidden_classes(cfg: dict):
    """Namen der Overlay-Klassen, die nicht in die VR gespiegelt werden."""
    lst = cfg.get("vr_hidden", []) or []
    return set(x for x in lst if isinstance(x, str))

# ---------------------------------------------------------------------------
# VRMirror: Shared Memory + Lebenszyklus
# ---------------------------------------------------------------------------

class VRMirror:
    """Haelt das PBVR-v2-Shared-Memory offen. publish(bgra) schreibt ein
    Leinwandbild (w*h*4 Bytes BGRA) und den Header mit neuem frame-Zaehler.
    Der Layer aktualisiert die Textur nur bei neuem Zaehler - publish() wird
    deshalb maximal 20x pro Sekunde aufgerufen (REFRESH_S, siehe too_soon)."""

    def __init__(self, w: int, h: int, cfg: dict = None):
        cfg = cfg or {}
        self.w = int(w)
        self.h = int(h)
        self.show_frame = bool(cfg.get("show_frame", True))
        self.opacity = min(1.0, max(0.05, float(cfg.get("vr_opacity", 100)) / 100.0))
        self.update_pose(cfg)
        self._k32 = None
        self._hmap = None
        self._view = None
        self._frame = 0
        self._last = 0.0

    def update_pose(self, cfg: dict):
        """Regler-Aenderungen uebernehmen (wirkt ab dem naechsten Bild)."""
        (self.quadW, self.quadH,
         self.posX, self.posY, self.posZ) = pose_from_config(cfg or {}, self.w, self.h)
        self.opacity = min(1.0, max(0.05, float((cfg or {}).get("vr_opacity", 100)) / 100.0))

    # -- Lebenszyklus -------------------------------------------------------

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            size = HEADER_SIZE + self.w * self.h * 4
            invalid = ctypes.c_void_p(-1).value  # INVALID_HANDLE_VALUE
            k32.CreateFileMappingW.restype = ctypes.c_void_p
            k32.CreateFileMappingW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.c_ulong, ctypes.c_ulong,
                                                ctypes.c_ulong, ctypes.c_wchar_p]
            h = k32.CreateFileMappingW(invalid, None, _PAGE_READWRITE, 0, size,
                                       MAPPING_NAME)
            if not h:
                return False
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                          ctypes.c_ulong, ctypes.c_ulong,
                                          ctypes.c_size_t]
            v = k32.MapViewOfFile(h, _FILE_MAP_ALL_ACCESS, 0, 0, size)
            if not v:
                k32.CloseHandle(ctypes.c_void_p(h))
                return False
            self._k32 = k32
            self._hmap = h
            self._view = v
            self._frame = 0
            self._write_header()
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

    def _write_header(self):
        if self._view:
            hdr = struct.pack(HEADER_FMT, MAGIC, PROTOCOL_VERSION,
                              self.w, self.h, self._frame,
                              self.quadW, self.quadH,
                              self.posX, self.posY, self.posZ)
            ctypes.memmove(self._view, hdr, HEADER_SIZE)

    def too_soon(self, now: float) -> bool:
        """True, wenn der letzte Spiegel noch keine REFRESH_S Sekunden alt ist."""
        return (now - self._last) < REFRESH_S

    def publish(self, bgra: bytes, now: float = None) -> bool:
        """Leinwandbild ins Shared Memory schreiben (frame-Zaehler erhoehen).
        Rueckgabe False, wenn das Mapping fehlt oder die Groesse nicht passt."""
        if not self._view:
            return False
        if len(bgra) != self.w * self.h * 4:
            return False
        self._frame = (self._frame + 1) & 0xFFFFFFFF
        self._write_header()
        ctypes.memmove(self._view + HEADER_SIZE, bgra, len(bgra))
        if now is not None:
            self._last = now
        return True

# ---------------------------------------------------------------------------
# Selftest (python vr_overlay.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ok = True

    def check(name, cond, info=""):
        global ok
        passed = bool(cond)
        print(("PASS" if passed else "FAIL"), "-", name, info if not passed else "")
        ok = ok and passed

    check("Header-Layout: 5 x uint32 + 5 x float = 40 Bytes", HEADER_SIZE == 40, HEADER_SIZE)
    check("Protokoll v2", PROTOCOL_VERSION == 2)

    hdr = struct.pack(HEADER_FMT, MAGIC, PROTOCOL_VERSION, 1920, 1080, 7,
                      1.5, 0.84, 0.0, 0.3, -1.2)
    check("Header packen (1920x1080 + Pose)", len(hdr) == 40)
    vals = struct.unpack(HEADER_FMT, hdr)
    floats_ok = all(abs(a - b) < 1e-6 for a, b in zip(vals[5:], [1.5, 0.84, 0.0, 0.3, -1.2]))
    check("Header entpacken", list(vals[:5]) == [MAGIC, 2, 1920, 1080, 7] and floats_ok, vals)

    w, h, s = canvas_size(1920, 1080)
    check("1:1-Aufloesung bleibt unskaliert", (w, h, s) == (1920, 1080, 1.0), (w, h, s))
    w4, h4, s4 = canvas_size(3840, 2160)
    check("4K bleibt 1:1 (Schärfe, 0.4.0.2)", (w4, h4, s4) == (3840, 2160, 1.0), (w4, h4, s4))
    w5, h5, s5 = canvas_size(5120, 2880)
    check("5K wird auf 4096 gedeckelt", (w5, h5) == (4096, 2304) and 0.0 < s5 < 1.0, (w5, h5, s5))

    cfg = dict(DEFAULTS)
    qw, qh, px, py, pz = pose_from_config(cfg, 1920, 1080)
    check("Pose: quadH folgt Seitenverhaeltnis", abs(qh - 1.6 * 1080 / 1920) < 1e-9, qh)
    check("Pose: Abstand negativ (vor dem Fahrer)", pz < 0, pz)
    qw2, qh2, _, _, _ = pose_from_config(dict(DEFAULTS, vr_width_m=3.0), 1000, 500)
    check("Pose: Hoehe passt sich bei anderem Format an", abs(qh2 - 1.5) < 1e-9, qh2)

    m = VRMirror(64, 64, DEFAULTS)
    check("VRMirror: publish ohne start() = False", m.publish(b"x" * (64 * 64 * 4)) is False)
    m._last = 100.0  # Basiszeit fuer den Drossel-Test
    check("VRMirror: zu frueh erkannt", m.too_soon(100.01) is True and m.too_soon(100.2) is False)

    print("SELTEST", "OK" if ok else "FEHLER")
    sys.exit(0 if ok else 1)
