# -*- coding: utf-8 -*-
"""Tests fuer das PBVR-v3-Protokollmodul (Overlays verwalten/kippen).
Qt-frei, laeuft ueberall:  python3 test_vr_overlay.py
0.4.2.0: komplette Neufassung fuer Protokoll v3 (eine Tafel je Overlay,
eigene Pose mit Abstand und Kippung statt einer Gesamt-Leinwand)."""

import math
import struct
import sys
import tempfile
from pathlib import Path

import vr_overlay as vo

cases = []


def case(fn):
    cases.append(fn)
    return fn


@case
def header_layout():
    """v3-Header: 5 x uint32, Little-Endian, 20 Bytes."""
    assert vo.PROTOCOL_VERSION == 3
    assert vo.HEADER_FMT == "<5I", vo.HEADER_FMT
    assert vo.HEADER_SIZE == 20, vo.HEADER_SIZE
    assert struct.calcsize(vo.HEADER_FMT) == 20


@case
def slot_layout():
    """Slot-Eintrag: 5 x uint32 + 7 x float = 48 Bytes; Tabelle passt."""
    assert vo.SLOT_FMT == "<5I7f", vo.SLOT_FMT
    assert vo.SLOT_SIZE == 48, vo.SLOT_SIZE
    assert vo.MAX_SLOTS == 16
    assert vo.DATA_START == 20 + 16 * 48 == 788, vo.DATA_START


@case
def build_message_roundtrip():
    """Header + Tabelle + Pixel: Offsets zeigen hinter die Tabelle."""
    px1 = bytes(bytearray([1, 2, 3, 4])) * (8 * 4)      # 8x4 BGRA
    px2 = bytes(bytearray([9, 9, 9, 255])) * (4 * 2)    # 4x2 BGRA
    slots = [{"w": 8, "h": 4, "pixels": px1,
              "quadW": 0.5, "quadH": 0.25, "posX": -0.2, "posY": 0.3,
              "posZ": -1.2, "pitch": 0.1, "yaw": -0.2},
             {"w": 4, "h": 2, "pixels": px2,
              "quadW": 0.1, "quadH": 0.05, "posX": 0.0, "posY": 0.0,
              "posZ": -2.0, "pitch": 0.0, "yaw": 0.0}]
    msg = vo.VRMirror.build_message(slots)
    assert len(msg) == vo.DATA_START + len(px1) + len(px2)
    magic, ver, frame, count, maxslots = struct.unpack_from(vo.HEADER_FMT, msg, 0)
    assert magic == vo.MAGIC and ver == 3 and frame == 0
    assert count == 2 and maxslots == vo.MAX_SLOTS
    u1, w1, h1, o1, _pad = struct.unpack_from("<5I", msg, 20)
    assert (u1, w1, h1) == (1, 8, 4)
    assert o1 == vo.DATA_START
    u2, w2, h2, o2, _pad = struct.unpack_from("<5I", msg, 20 + 48)
    assert (u2, w2, h2) == (1, 4, 2)
    assert o2 == vo.DATA_START + len(px1)
    # dritter Slot: unbenutzt
    u3 = struct.unpack_from("<I", msg, 20 + 2 * 48)[0]
    assert u3 == 0
    # Pixel liegen am Offset
    assert msg[o1:o1 + 4] == bytes(bytearray([1, 2, 3, 4]))
    assert msg[o2:o2 + 4] == bytes(bytearray([9, 9, 9, 255]))


@case
def build_message_ablehnungen():
    """Zu viele Slots, falsche Pixel-Laenge und unzulaessige Groessen."""
    def slot(**kw):
        d = {"w": 2, "h": 2, "pixels": b"x" * 16, "quadW": 0.1, "quadH": 0.1,
             "posX": 0.0, "posY": 0.0, "posZ": -1.0, "pitch": 0.0, "yaw": 0.0}
        d.update(kw)
        return d
    try:
        vo.VRMirror.build_message([slot()] * (vo.MAX_SLOTS + 1))
        assert False, "zu viele Slots nicht abgelehnt"
    except ValueError:
        pass
    try:
        vo.VRMirror.build_message([slot(pixels=b"x" * 8)])
        assert False, "falsche Pixel-Laenge nicht abgelehnt"
    except ValueError:
        pass
    try:
        vo.VRMirror.build_message([slot(w=0)])
        assert False, "w=0 nicht abgelehnt"
    except ValueError:
        pass
    # leere Liste ist erlaubt (raeumt alle Tafeln weg)
    msg = vo.VRMirror.build_message([])
    assert len(msg) == vo.DATA_START
    assert struct.unpack_from("<I", msg, 8)[0] == 0  # count = 0


@case
def canvas_size_1zu1():
    """Normale Aufloesung wird unskaliert uebernommen."""
    assert vo.canvas_size(1920, 1080) == (1920, 1080, 1.0)
    assert vo.canvas_size(3440, 1440) == (3440, 1440, 1.0)


@case
def canvas_size_deckel():
    """4K bleibt 1:1 scharf; erst ab 4096 wird gedeckelt."""
    assert vo.canvas_size(3840, 2160) == (3840, 2160, 1.0)
    w, h, s = vo.canvas_size(5120, 2880)
    assert (w, h) == (4096, 2304), (w, h)
    assert 0.0 < s < 1.0


@case
def board_pose_werte():
    """Diagnose-Tafel: Breite aus Regler, Hoehe aus Seitenverhaeltnis."""
    qw, qh, px, py, pz, pitch, yaw = vo.board_pose(dict(vo.DEFAULTS), 1920, 1080)
    assert abs(qw - 1.6) < 1e-9
    assert abs(qh - 1.6 * 1080 / 1920) < 1e-9
    assert px == 0.0 and abs(py - 0.35) < 1e-9
    assert abs(pz + 1.2) < 1e-9  # Abstand negativ (vor dem Fahrer)
    assert pitch == 0.0 and yaw == 0.0


@case
def overlay_pose_position():
    """Mitte links/rechts wird in Meter umgerechnet, Hoehe folgt v."""
    cfg = dict(vo.DEFAULTS)
    # Bildmitte -> pos_x 0
    _, _, px, py, _, _, _ = vo.overlay_pose(cfg, 1000, 500, 500.0, 250.0, 10, 5)
    assert abs(px) < 1e-9
    assert abs(py - 0.35) < 1e-9
    # rechts der Mitte -> pos_x > 0, unterhalb der Mitte -> pos_y < 0
    _, _, px2, py2, _, _, _ = vo.overlay_pose(cfg, 1000, 500, 750.0, 375.0, 10, 5)
    assert px2 > 0
    assert py2 < 0.35


@case
def tilt_from_config():
    """Kippung in Grad -> Radiant, geklemmt auf +-60 Grad."""
    cfg = dict(vo.DEFAULTS, vr_tilt={"A": (30.0, -45.0)})
    p, y = vo.tilt_from_config(cfg, "A")
    assert abs(p - math.radians(30.0)) < 1e-9
    assert abs(y - math.radians(-45.0)) < 1e-9
    # fehlend / Muell -> 0/0
    assert vo.tilt_from_config(cfg, "B") == (0.0, 0.0)
    # ueber Bereich geklemmt, ungueltige Eintraege -> 0/0
    p2, y2 = vo.tilt_from_config(dict(vo.DEFAULTS, vr_tilt={"A": (999, -999)}), "A")
    assert p2 == math.radians(60.0) and y2 == math.radians(-60.0)
    assert vo.tilt_from_config(dict(vo.DEFAULTS, vr_tilt={"A": (None, "x")}), "A") == (0.0, 0.0)


@case
def depth_from_config():
    """Abstands-Faktor 0.5..2.0, Standard 1.0."""
    cfg = dict(vo.DEFAULTS, vr_depth={"A": 1.5, "B": 0.3})
    assert abs(vo.depth_from_config(cfg, "A") - 1.5) < 1e-9
    assert abs(vo.depth_from_config(cfg, "B") - 0.5) < 1e-9  # geklemmt
    assert vo.depth_from_config(cfg, "C") == 1.0


@case
def mode_of_und_filter():
    """Anzeige-Modus + hidden/vronly-Filter (nur Strings zaehlen)."""
    cfg = {"vr_hidden": ["A"], "vr_vronly": ["B"]}
    assert vo.mode_of(cfg, "A") == "monitor"
    assert vo.mode_of(cfg, "B") == "vr"
    assert vo.mode_of(cfg, "C") == "both"
    assert vo.hidden_classes(cfg) == {"A"}
    assert vo.vronly_classes(cfg) == {"B"}
    assert vo.hidden_classes({"vr_hidden": ["A", 5, None]}) == {"A"}
    assert vo.vronly_classes({}) == set()


@case
def config_roundtrip():
    """Speichern + Laden inklusive vr_hidden/vr_vronly/vr_tilt und Merge."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "vr_overlay.json"
        cfg = vo.load_config(p)
        assert cfg == dict(vo.DEFAULTS), cfg
        vo.save_config(p, {"vr_width_m": 2.5, "vr_opacity": 80,
                           "vr_hidden": ["DeltaBoard"],
                           "vr_vronly": ["FuelBoard"],
                           "vr_tilt": {"FuelBoard": [15.0, -10.0]}})
        cfg = vo.load_config(p)
        assert cfg["vr_width_m"] == 2.5 and cfg["vr_opacity"] == 80
        assert cfg["vr_hidden"] == ["DeltaBoard"]
        assert cfg["vr_vronly"] == ["FuelBoard"]
        assert cfg["vr_tilt"]["FuelBoard"] == [15.0, -10.0]
        assert cfg["show_frame"] is True  # DEFAULTS bleiben erhalten
        assert cfg["vr_backdrop"] == vo.DEFAULTS["vr_backdrop"]
        # verfaelschte Datei: DEFAULTS ueberleben
        p.write_text("{}", encoding="utf-8")
        assert vo.load_config(p)["vr_dist_m"] == vo.DEFAULTS["vr_dist_m"]


@case
def mirror_ohne_start():
    """publish_slots() ohne Shared Memory (Nicht-Windows) = False."""
    m = vo.VRMirror(vo.DEFAULTS)
    assert m.start() is False or sys.platform == "win32"
    slot = {"w": 2, "h": 2, "pixels": b"x" * 16, "quadW": 0.1, "quadH": 0.1,
            "posX": 0.0, "posY": 0.0, "posZ": -1.0, "pitch": 0.0, "yaw": 0.0}
    assert m.publish_slots([slot]) is False
    assert m.publish_slots([]) is False
    m.stop()  # darf nie crashen


@case
def mirror_throttle():
    """too_soon haelt 10 Bilder/s ein (0.4.1.1)."""
    m = vo.VRMirror(vo.DEFAULTS)
    m._last = 100.0
    assert m.too_soon(100.04) is True
    assert m.too_soon(100.15) is False


@case
def mirror_pose_update():
    """update_pose uebernimmt die globale Deckkraft sofort."""
    m = vo.VRMirror(vo.DEFAULTS)
    assert abs(m.opacity - 1.0) < 1e-9
    m.update_pose({"vr_opacity": 50})
    assert abs(m.opacity - 0.5) < 1e-9


@case
def defaults_v3():
    """0.4.2.0: vr_vronly und vr_tilt sind Teil der DEFAULTS."""
    assert vo.DEFAULTS.get("vr_vronly") == []
    assert vo.DEFAULTS.get("vr_tilt") == {}
    assert vo.DEFAULTS.get("vr_zoom") == 1.0
    assert vo.DEFAULTS.get("vr_gain") == 100


def main():
    failed = 0
    for fn in cases:
        try:
            fn()
            print("PASS -", fn.__name__)
        except AssertionError as exc:
            failed += 1
            print("FAIL -", fn.__name__, "-", exc)
        except Exception as exc:  # noqa
            failed += 1
            print("ERROR -", fn.__name__, "-", type(exc).__name__, exc)
    print("%d/%d Tests OK" % (len(cases) - failed, len(cases)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
