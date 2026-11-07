# -*- coding: utf-8 -*-
"""Tests fuer das PBVR-v2-Protokollmodul (Monitor-Spiegel).
Qt-frei, laeuft ueberall:  python3 test_vr_overlay.py"""

import struct
import sys
import tempfile
from pathlib import Path

import vr_overlay as vo

HDR = vo.HEADER_FMT          # "<5I5f"
HDR_SIZE = vo.HEADER_SIZE    # 40

cases = []


def case(fn):
    cases.append(fn)
    return fn


@case
def header_layout():
    """v2-Header: 5 x uint32 + 5 x float, Little-Endian, 40 Bytes."""
    assert HDR == "<5I5f", HDR
    assert HDR_SIZE == 40, HDR_SIZE
    assert struct.calcsize(HDR) == 40


@case
def header_roundtrip():
    """Header packen/entpacken inklusive Pose-Floats."""
    hdr = struct.pack(HDR, vo.MAGIC, 2, 1920, 1080, 1234,
                      1.6, 0.9, 0.0, 0.35, -1.2)
    assert len(hdr) == 40
    magic, ver, w, h, frame, qw, qh, px, py, pz = struct.unpack(HDR, hdr)
    assert (magic, ver, w, h, frame) == (vo.MAGIC, 2, 1920, 1080, 1234)
    assert abs(qw - 1.6) < 1e-6 and abs(qh - 0.9) < 1e-6
    assert px == 0.0 and abs(py - 0.35) < 1e-6 and abs(pz + 1.2) < 1e-6


@case
def canvas_size_1zu1():
    """Normale Aufloesung wird unskaliert uebernommen."""
    assert vo.canvas_size(1920, 1080) == (1920, 1080, 1.0)
    assert vo.canvas_size(2560, 1440) == (2560, 1440, 1.0)


@case
def canvas_size_deckel():
    """4K wird auf 2560x1440 gedeckelt (Speicherschutz)."""
    w, h, s = vo.canvas_size(3840, 2160)
    assert (w, h) == (2560, 1440), (w, h)
    assert 0.0 < s < 1.0


@case
def pose_seitenverhaeltnis():
    """quadH folgt dem Leinwand-Seitenverhaeltnis; Abstand negativ."""
    qw, qh, px, py, pz = vo.pose_from_config(dict(vo.DEFAULTS), 1920, 1080)
    assert abs(qw - 1.6) < 1e-9
    assert abs(qh - 1.6 * 1080 / 1920) < 1e-9
    assert px == 0.0 and abs(py - 0.35) < 1e-9
    assert pz == -1.2 or abs(pz + 1.2) < 1e-9


@case
def pose_anderes_format():
    """Bei 1000x500 wird die Tafel proportional angepasst."""
    _, qh, _, _, _ = vo.pose_from_config(dict(vo.DEFAULTS, vr_width_m=2.0), 1000, 500)
    assert abs(qh - 1.0) < 1e-9, qh


@case
def config_roundtrip():
    """Speichern + Laden inklusive vr_hidden und DEFAULTS-Merge."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "vr_overlay.json"
        cfg = vo.load_config(p)
        assert cfg == dict(vo.DEFAULTS), cfg
        vo.save_config(p, {"vr_width_m": 2.5, "vr_opacity": 80,
                           "vr_hidden": ["DeltaBoard"]})
        cfg = vo.load_config(p)
        assert cfg["vr_width_m"] == 2.5 and cfg["vr_opacity"] == 80
        assert cfg["vr_hidden"] == ["DeltaBoard"]
        assert cfg["show_frame"] is True  # DEFAULTS bleiben erhalten
        # verfaelschte Datei: DEFAULTS ueberleben
        p.write_text("{}", encoding="utf-8")
        assert vo.load_config(p)["vr_dist_m"] == vo.DEFAULTS["vr_dist_m"]


@case
def hidden_classes_filter():
    """Nur Strings zaehlen; Liste darf fehlen oder None sein."""
    assert vo.hidden_classes({"vr_hidden": ["A", "B"]}) == {"A", "B"}
    assert vo.hidden_classes({}) == set()
    assert vo.hidden_classes({"vr_hidden": ["A", 5, None]}) == {"A"}


@case
def mirror_ohne_start():
    """publish() ohne Shared Memory (Nicht-Windows/ohne start) = False."""
    m = vo.VRMirror(64, 64, vo.DEFAULTS)
    assert m.start() is False or sys.platform == "win32"
    assert m.publish(b"x" * (64 * 64 * 4)) is False
    assert m.publish(b"x" * 8) is False  # falsche Groesse
    m.stop()  # darf nie crashen


@case
def mirror_throttle():
    """too_soon haelt 20 Bilder/s ein."""
    m = vo.VRMirror(64, 64, vo.DEFAULTS)
    m._last = 100.0
    assert m.too_soon(100.04) is True
    assert m.too_soon(100.06) is False


@case
def mirror_pose_update():
    """update_pose uebernimmt Reglerwerte sofort (Abstand negativ)."""
    m = vo.VRMirror(1920, 1080, vo.DEFAULTS)
    m.update_pose({"vr_width_m": 3.0, "vr_height_m": 0.5,
                   "vr_dist_m": 2.0, "vr_opacity": 50})
    assert abs(m.quadW - 3.0) < 1e-9
    assert abs(m.quadH - 3.0 * 1080 / 1920) < 1e-9
    assert abs(m.posZ + 2.0) < 1e-9
    assert abs(m.opacity - 0.5) < 1e-9


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
            print("ERROR -", fn.__name__, "-", exc)
    print("%d/%d Tests OK" % (len(cases) - failed, len(cases)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
