# -*- coding: utf-8 -*-
"""
PitBoss R3E - VR-Overlay (Toter-Winkel-Tafel)
=============================================
Schreibt das Bild der VR-Tafel in das Shared Memory, aus dem der OpenXR-
API-Layer im Spiel (XR_APILAYER_PitBossR3E_VR.dll, siehe vr_layer/) liest.

PBVR-Protokoll v1 (identisch zum Layer, siehe vr_layer/README.md):
  Header, 5 x uint32 im Little-Endian-Layout:
    [0] magic   = 0x52564250  ("PBVR" little-endian)
    [1] version = 1
    [2] width   = 512
    [3] height  = 256
    [4] frame   = laufende Bildnummer (Lebenszeichen/Diagnose)
  Danach: width * height Pixel, je 4 Bytes in der Reihenfolge B, G, R, A.

Der Layer prueft magic/version/masse und kopiert die Pixel in seine Swapchain.
Laeuft PitBoss nicht (oder ist das Mapping weg), zeigt der Layer sein
Testmuster mit wanderndem Balken - die Tafel bleibt also immer sichtbar.

Dieses Modul ist absichtlich frei von PySide6: Shared-Memory-Anlage,
Toter-Winkel-Berechnung und Bild-Renderer sind pur und per Selftest
(test_vr_overlay.py) pruefbar.
"""

import ctypes
import json
import struct
import sys

# ---------------------------------------------------------------------------
# Protokoll-Konstanten (muessen zum Layer passen)
# ---------------------------------------------------------------------------

MAGIC = 0x52564250          # "PBVR" little-endian
PROTOCOL_VERSION = 1
BOARD_W = 512
BOARD_H = 256
HEADER_FMT = "<5I"          # magic, version, width, height, frame
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAPPING_NAME = "Local\\PitBossR3E_VR"   # sitzungsgleich mit dem Spielprozess

_PAGE_READWRITE = 0x04
_FILE_MAP_ALL_ACCESS = 0xF001F

# ---------------------------------------------------------------------------
# Konfiguration (vr_overlay.json: aktiv + Leinwand-Rahmen)
# ---------------------------------------------------------------------------

def load_config(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(path, updates: dict) -> dict:
    cfg = load_config(path)
    cfg.update(updates)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass
    return cfg

# ---------------------------------------------------------------------------
# Toter-Winkel-Tracker
# ---------------------------------------------------------------------------

class BlindSpotTracker:
    """Zustandstracker fuer die VR-Tafel. Bewusst dieselbe Heuristik wie das
    Desktop-Overlay (BlindSpotOverlayWindow in main.py): Das Shared Memory
    liefert keine verlaessliche Fahrzeug-Orientierung, deshalb wird die
    Fahrtrichtung aus der Positionsaenderung geglaettet. thresholds identisch:
    MAX_DIST 12 m, |Laengsversatz| <= 6 m, Querabstand 1.0..5.5 m. Nur in
    Bewegung (Geschwindigkeit > 12 km/h, Wegstueck > 0.25 m) wird der
    Richtungsvektor nachgefuehrt - steht das Auto, bleibt der letzte Stand.
    flip (Seiten spiegeln) entspricht der Desktop-Einstellung.
    """

    MAX_DIST = 12.0
    FWD_MAX = 6.0
    LAT_MIN = 1.0
    LAT_MAX = 5.5

    def __init__(self, flip: bool = True):
        self.flip = bool(flip)
        self.left = False
        self.right = False
        self._prev = None
        self._hx = 0.0
        self._hz = 0.0

    @property
    def state(self):
        return (self.left, self.right)

    def update(self, s):
        self.left = self.right = False
        if s is None:
            return self.state
        px = float(getattr(s, "pos_x", 0.0) or 0.0)
        pz = float(getattr(s, "pos_z", 0.0) or 0.0)
        spd = float(getattr(s, "speed_kmh", 0.0) or 0.0)
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
            return self.state
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
            fwd = relx * hx + relz * hz
            cross = relx * hz - relz * hx
            lat = abs(cross)
            if abs(fwd) > self.FWD_MAX or lat < self.LAT_MIN or lat > self.LAT_MAX:
                continue
            left = cross > 0
            if self.flip:
                left = not left
            if left:
                self.left = True
            else:
                self.right = True
        return self.state

# ---------------------------------------------------------------------------
# Renderer (512x256 BGRA, PySide-frei)
# ---------------------------------------------------------------------------

# BGRA-Farben
_PANEL = (24, 24, 28, 140)         # halbtransparent dunkel
_PANEL_LINE = (70, 70, 84, 110)
_AMBER = (35, 166, 245, 255)        # #f5a623 in B,G,R
_AMBER_DIM = (52, 88, 122, 150)     # inaktiv: gedaempfte Kontur
_FRAME_A = (208, 208, 208, 170)     # Leinwand-Rahmen hell
_FRAME_B = (60, 60, 60, 90)         # Leinwand-Rahmen dunkel (Schraffur)


def _set(buf, w, h, x, y, c):
    if 0 <= x < w and 0 <= y < h:
        i = (y * w + x) * 4
        buf[i] = c[0]
        buf[i + 1] = c[1]
        buf[i + 2] = c[2]
        buf[i + 3] = c[3]


def _fill_rect(buf, w, h, x0, y0, x1, y1, c):
    for y in range(max(0, y0), min(h, y1)):
        base = y * w * 4
        row = bytes(c) * (x1 - x0)
        i = base + max(0, x0) * 4
        buf[i:i + len(row)] = row


def _in_tri(px, py, ax, ay, bx, by, cx, cy):
    d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def _draw_tri(buf, w, h, a, b, c, fill, outline):
    """Gefuelltes Dreieck (Pfeilspitze) mit Kontur."""
    a, b, c = [(int(v[0]), int(v[1])) for v in (a, b, c)]
    xs = (a[0], b[0], c[0])
    ys = (a[1], b[1], c[1])
    for y in range(max(0, min(ys) - 1), min(h, max(ys) + 2)):
        for x in range(max(0, min(xs) - 1), min(w, max(xs) + 2)):
            if _in_tri(x + 0.5, y + 0.5, a[0], a[1], b[0], b[1], c[0], c[1]):
                _set(buf, w, h, x, y, fill)
    _draw_line(buf, w, h, a, b, outline)
    _draw_line(buf, w, h, b, c, outline)
    _draw_line(buf, w, h, c, a, outline)


def _draw_line(buf, w, h, p0, p1, c):
    """Bresenham-Linie."""
    x0, y0 = p0
    x1, y1 = p1
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        _set(buf, w, h, x, y, c)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def render_board(left: bool, right: bool, show_frame: bool = True,
                 w: int = BOARD_W, h: int = BOARD_H) -> bytes:
    """Baut das Tafelbild (BGRA). Zwei Pfeile links/rechts wie im Desktop-
    Overlay: bernsteinfarben gefuellt, wenn ein Auto im toten Winkel steht,
    sonst nur gedaempfte Kontur. Der schraffierte Leinwand-Rahmen (Marcels
    Wunsch: zeigt die VR-Leinwand, abschaltbar) umrandet die Tafel."""
    buf = bytearray(w * h * 4)   # komplett transparent (A=0)

    # Panel: abgerundete Box mit Rand
    m = 12
    _fill_rect(buf, w, h, m + 3, m + 3, w - m - 3, h - m - 3, _PANEL)
    for x in range(m, w - m):
        for e in range(3):
            _set(buf, w, h, x, m + e, _PANEL_LINE)
            _set(buf, w, h, x, h - 1 - m - e, _PANEL_LINE)
    for y in range(m, h - m):
        for e in range(3):
            _set(buf, w, h, m + e, y, _PANEL_LINE)
            _set(buf, w, h, w - 1 - m - e, y, _PANEL_LINE)

    # Pfeile: Spitze zeigt nach AUSSEN (links links, rechts rechts),
    # wie Blick in die Seitenspiegel. Aktiver Pfeil: gefuellt amber.
    cy = h // 2
    ax_w = int(h * 0.22)          # Pfeilbreite (Halbe)
    ax_h = int(h * 0.30)          # Pfeilhoehe (Halbe)
    lx = int(w * 0.30)            # Mitte linker Pfeil
    rx = int(w * 0.70)            # Mitte rechter Pfeil
    lc = _AMBER if left else _AMBER_DIM
    rc = _AMBER if right else _AMBER_DIM
    # linker Pfeil: Spitze links
    _draw_tri(buf, w, h, (lx - ax_w, cy), (lx + ax_w * 0.7, cy - ax_h), (lx + ax_w * 0.7, cy + ax_h), lc, lc)
    # rechter Pfeil: Spitze rechts
    _draw_tri(buf, w, h, (rx + ax_w, cy), (rx - ax_w * 0.7, cy - ax_h), (rx - ax_w * 0.7, cy + ax_h), rc, rc)

    # Leinwand-Rahmen: 4 px schraffierter Rand (abschaltbar)
    if show_frame:
        band = 4
        for y in range(h):
            for x in range(w):
                edge = x < band or x >= w - band or y < band or y >= h - band
                if edge:
                    c = _FRAME_A if ((x + y) % 8) < 4 else _FRAME_B
                    _set(buf, w, h, x, y, c)
    return bytes(buf)

# ---------------------------------------------------------------------------
# VRBoard: Shared Memory + Lebenszyklus
# ---------------------------------------------------------------------------

class VRBoard:
    """Haelt das PBVR-Shared-Memory offen und aktualisiert die Tafel.
    tick() wird aus der Overlay-Aktualisierung von main.py (10-20 Hz) im
    Qt-Hauptthread aufgerufen - kein eigener Thread noetig. start() legt das
    Mapping an und liefert False, wenn das nicht moeglich ist (z. B. ohne
    Windows); PitBoss laeuft dann ohne VR-Tafel weiter."""

    def __init__(self, show_frame: bool = True, flip: bool = True):
        self.show_frame = bool(show_frame)
        self.tracker = BlindSpotTracker(flip=flip)
        self._k32 = None
        self._hmap = None
        self._view = None
        self._frame = 0
        self._last = None

    # -- Lebenszyklus -------------------------------------------------------

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            size = HEADER_SIZE + BOARD_W * BOARD_H * 4
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
            self.redraw(force=True)
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
                              BOARD_W, BOARD_H, self._frame)
            ctypes.memmove(self._view, hdr, HEADER_SIZE)

    def redraw(self, force: bool = False):
        """Neu rendern, wenn sich der Zustand (oder der Rahmen-Modus) geaendert hat."""
        state = self.tracker.state
        if not force and state == self._last:
            return
        self._last = state
        pixels = render_board(state[0], state[1], self.show_frame)
        if self._view:
            ctypes.memmove(self._view + HEADER_SIZE, pixels, len(pixels))

    def tick(self, main):
        """Aufruf aus der Overlay-Aktualisierung: Toter-Winkel-Zustand
        nachfuehren, Bild bei Aenderung neu schreiben, frame-zaehler
        inkrementieren (Lebenszeichen im Header)."""
        s = getattr(main, "last_live_sample", None)
        if s is None:
            samples = getattr(main, "samples", None)
            s = samples[-1] if samples else None
        self.tracker.update(s)
        self.redraw()
        self._frame = (self._frame + 1) & 0xFFFFFFFF
        self._write_header()

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

    check("Header-Layout: 5 x uint32 = 20 Bytes", HEADER_SIZE == 20, HEADER_SIZE)
    check("Board-Masse 512x256", (BOARD_W, BOARD_H) == (512, 256))
    check("Magic", MAGIC == 0x52564250)

    img = render_board(True, False, True)
    check("Bildgroesse", len(img) == BOARD_W * BOARD_H * 4, len(img))
    li = ((BOARD_H // 2) * BOARD_W + int(BOARD_W * 0.30)) * 4  # linker Pfeil aktiv
    check("Linker Pfeil amber", img[li + 3] == 255, img[li:li + 4])
    ri = ((BOARD_H // 2) * BOARD_W + int(BOARD_W * 0.70)) * 4  # rechter Pfeil inaktiv
    check("Rechter Pfeil gedimmt", img[ri + 3] == 150, img[ri:ri + 4])
    fi = (2 * BOARD_W + 2) * 4  # Rahmenecke
    check("Leinwand-Rahmen sichtbar", img[fi + 3] > 0, img[fi:fi + 4])
    img2 = render_board(True, False, False)
    check("Rahmen abschaltbar (Ecke transparent)", img2[fi + 3] == 0, img2[fi:fi + 4])

    tr = BlindSpotTracker(flip=True)
    check("Tracker Startzustand", tr.state == (False, False))

    class S:
        pos_x = 0.0
        pos_z = 0.0
        speed_kmh = 0.0
        opponents = ()
        def __init__(self, x, z, v, opps):
            self.pos_x, self.pos_z, self.speed_kmh, self.opponents = x, z, v, opps

    tr.update(S(0.0, 0.0, 0.0, ()))
    tr.update(S(10.0, 0.0, 100.0, ((1, 10.0, 3.0, False),)))  # Bewegung +x, Gegner quer
    check("Tracker: Gegner erkannt", tr.state[0] or tr.state[1], tr.state)

    print("SELTEST", "OK" if ok else "FEHLER")
    sys.exit(0 if ok else 1)
