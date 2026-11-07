# -*- coding: utf-8 -*-
"""Selftest fuer vr_overlay.py: PBVR-Protokoll, Renderer, Tracker, Konfiguration.

Aufruf:  python test_vr_overlay.py   -> PASS/FAIL pro Fall, Exit-Code 0/1.

Der Test ist bewusst frei von Windows-API-Aufrufen: VRBoard.start() wird nur
auf Nicht-Windows-Plattformen geprueft (muss False liefern); das echte
Mapping wird im Praxistest mit dem VR-Layer verifiziert.
"""

import sys
import tempfile
from pathlib import Path

from vr_overlay import (BlindSpotTracker, BOARD_H, BOARD_W, HEADER_FMT,
                        HEADER_SIZE, MAGIC, MAPPING_NAME, PROTOCOL_VERSION,
                        VRBoard, load_config, render_board, save_config)

CASES = []


def case(name, fn):
    CASES.append((name, fn))


# --- PBVR-Protokoll (muss zum C++-Layer passen) ------------------------------

case("Header: 5 x uint32 (Little Endian) = 20 Bytes",
     lambda: HEADER_SIZE == 20)

case("Magic 0x52564250 ('PBVR' little-endian)",
     lambda: MAGIC == 0x52564250)

case("Protokoll-Version 1", lambda: PROTOCOL_VERSION == 1)

case("Tafel-Masse 512x256 (kTexWidth/kTexHeight des Layers)",
     lambda: (BOARD_W, BOARD_H) == (512, 256))

case("Mapping-Name Local\\PitBossR3E_VR wie im Layer",
     lambda: MAPPING_NAME == "Local\\PitBossR3E_VR")

case("Header packen: magic, version, w, h, frame",
     lambda: list(__import__("struct").unpack(HEADER_FMT,
         __import__("struct").pack(HEADER_FMT, MAGIC, PROTOCOL_VERSION,
                                   BOARD_W, BOARD_H, 7)))
         == [MAGIC, PROTOCOL_VERSION, BOARD_W, BOARD_H, 7])


# --- Renderer ----------------------------------------------------------------

def _px(img, x, y):
    i = (y * BOARD_W + x) * 4
    return tuple(img[i:i + 4])


case("Bildgroesse = 512*256*4 Bytes",
     lambda: len(render_board(False, False)) == BOARD_W * BOARD_H * 4)

case("Hintergrund transparent (A=0) statt schwarz",
     lambda: _px(render_board(False, False, False), BOARD_W // 2, 6)[3] == 0)

case("Aktiver linker Pfeil bernsteinfarben (BGRA: R=0xF5)",
     lambda: _px(render_board(True, False), int(BOARD_W * 0.30), BOARD_H // 2)
         == (35, 166, 245, 255))

case("Inaktiver rechter Pfeil nur Kontur (halbtransparent)",
     lambda: _px(render_board(True, False), int(BOARD_W * 0.70), BOARD_H // 2)
         == (52, 88, 122, 150))

case("Aktiver rechter Pfeil bernsteinfarben",
     lambda: _px(render_board(False, True), int(BOARD_W * 0.70), BOARD_H // 2)
         == (35, 166, 245, 255))

case("Leinwand-Rahmen sichtbar (Ecke > A 0)",
     lambda: _px(render_board(False, False, True), 2, 2)[3] > 0)

case("Leinwand-Rahmen abschaltbar (Ecke voll transparent)",
     lambda: _px(render_board(False, False, False), 2, 2)[3] == 0)

case("Rahmen ist Schraffur (helle und dunkle Pixel im Band)",
     lambda: len({_px(render_board(False, False, True), 0, y)[3]
                  for y in range(0, 16)}) == 2)

case("Bild veraendert sich mit dem Zustand",
     lambda: render_board(True, True) != render_board(False, False))


# --- Toter-Winkel-Tracker (Heuristik wie das Desktop-Overlay) ---------------

class _Sample:
    """Minimaler Sample-Stub mit den Feldern, die der Tracker liest."""
    def __init__(self, x, z, v, opps=()):
        self.pos_x, self.pos_z = x, z
        self.speed_kmh = v
        self.opponents = opps


def _driving_tracker(opps, flip=False):
    """Tracker, der schon Fahrt aufgebaut hat (Bewegung nach +x, 100 km/h).

    Seitenkonvention (gilt im Desktop-Overlay seit 0.5.9.16, in echt validiert):
    Bei Bewegung nach +x und flip=True liegt +z LINKS vom Fahrer, -z RECHTS.
    """
    tr = BlindSpotTracker(flip=flip)
    tr.update(_Sample(0.0, 0.0, 0.0))
    tr.update(_Sample(10.0, 0.0, 100.0, opps))
    return tr


case("Stillstand: keine Richtung, keine Warnung",
     lambda: BlindSpotTracker().update(_Sample(0, 0, 0, ((1, 2.0, 2.0, False),)))
         == (False, False))

case("Bewegung +x, Gegner bei +z: LINKER Pfeil (flip=True, Fahrersicht)",
     lambda: _driving_tracker(((1, 10.0, 3.0, False),), flip=True).state
         == (True, False))

case("Bewegung +x, Gegner bei -z: RECHTER Pfeil (flip=True, Fahrersicht)",
     lambda: _driving_tracker(((1, 10.0, -3.0, False),), flip=True).state
         == (False, True))

case("flip=False vertauscht die Seiten (Rohwert cross>0 = rechts)",
     lambda: _driving_tracker(((1, 10.0, 3.0, False),), flip=False).state
         == (False, True))

case("Gegner in der Box wird ignoriert",
     lambda: _driving_tracker(((1, 10.0, 3.0, True),)).state == (False, False))

case("Gegner zu weit weg (> 12 m) wird ignoriert",
     lambda: _driving_tracker(((1, 40.0, 20.0, False),)).state == (False, False))

case("Gegner weit neben der Spur (quer > 5.5 m) wird ignoriert",
     lambda: _driving_tracker(((1, 10.0, 8.0, False),)).state == (False, False))

case("Gegner direkt daneben (quer < 1.0 m) wird ignoriert",
     lambda: _driving_tracker(((1, 10.0, 0.4, False),)).state == (False, False))

case("None-Sample laesst den Zustand unberuehrt",
     lambda: (lambda tr: (tr.update(None), tr.state == (False, False))[-1])(
         BlindSpotTracker()))


# --- VRBoard / Konfiguration -------------------------------------------------

case("VRBoard.start() auf Nicht-Windows: False (kein Crash)",
     lambda: (sys.platform == "win32") or (VRBoard().start() is False))

case("VRBoard.stop() ohne start(): kein Crash",
     lambda: (VRBoard().stop(), True)[1])


def _cfg_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "vr_overlay.json"
        save_config(p, {"enabled": True})
        save_config(p, {"show_frame": False})
        cfg = load_config(p)
        return cfg == {"enabled": True, "show_frame": False}


case("Konfiguration schreiben/lesen (aktiv + Rahmen)",
     _cfg_roundtrip)

case("load_config bei fehlender Datei: leeres dict",
     lambda: load_config(Path("GibtEsNicht_4712.json")) == {})


# --- Ausfuehrung --------------------------------------------------------------

if __name__ == "__main__":
    ok = True
    for name, fn in CASES:
        try:
            passed = bool(fn())
        except Exception as e:  # noqa: BLE001
            passed = False
            name += f" [{type(e).__name__}: {e}]"
        print(("PASS" if passed else "FAIL"), "-", name)
        ok = ok and passed
    print(f"{len(CASES)} Faelle,", "OK" if ok else "FEHLER")
    sys.exit(0 if ok else 1)
