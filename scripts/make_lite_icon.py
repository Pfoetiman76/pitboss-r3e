#!/usr/bin/env python3
"""Erzeugt assets/pitboss_app_icon_lite.ico aus assets/pitboss_app_icon.ico.

Das Lite-Icon = Original-Icon + tuerkises "LITE"-Banner unten (95 % Deckkraft,
PitBoss-Tuerkis #00e5ff, dunkle Schrift #04222b). Wird vom Release-Workflow vor
dem Inno-Setup-Schritt aufgerufen; setup.iss referenziert es per #ifdef LITE.
Reine Standardbibliothek - keine Pillow noetig. Alle sechs Groessen
(16/32/48/64/128/256) werden einzeln verarbeitet und neu kodiert.
"""
import struct
import zlib
from pathlib import Path

SRC = Path("assets/pitboss_app_icon.ico")
DST = Path("assets/pitboss_app_icon_lite.ico")
TURQ = (0x00, 0xE5, 0xFF)
INK = (0x04, 0x22, 0x2B)
# Buchstaben als Rechtecke (x0, y0, x1, y1) in Einheiten der Schrifthoehe
GLYPHS = {
    "L": (0.56, [(0.00, 0.00, 0.20, 1.00), (0.00, 0.80, 0.56, 1.00)]),
    "I": (0.28, [(0.04, 0.00, 0.24, 1.00)]),
    "T": (0.56, [(0.00, 0.00, 0.56, 0.20), (0.18, 0.00, 0.38, 1.00)]),
    "E": (0.52, [(0.00, 0.00, 0.20, 1.00), (0.00, 0.00, 0.52, 0.20),
                 (0.00, 0.40, 0.46, 0.60), (0.00, 0.80, 0.52, 1.00)]),
}
GAP = 0.10


def decode_png(data):
    """8-Bit-RGBA-PNG ohne Interlace dekodieren, Pixel als bytes zurueck."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "kein PNG"
    pos, idat, w, h = 8, b"", None, None
    while pos < len(data):
        ln, typ_ = struct.unpack(">I4s", data[pos:pos + 8])
        pos += 8
        chunk = data[pos:pos + ln]
        pos += ln + 4
        if typ_ == b"IHDR":
            w, h, bitd, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunk)
            assert bitd == 8 and ctype == 6 and interlace == 0, (bitd, ctype, interlace)
        elif typ_ == b"IDAT":
            idat += chunk
        elif typ_ == b"IEND":
            break
    raw = zlib.decompress(idat)
    stride = w * 4
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        filt = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if filt == 1:
            for x in range(4, stride):
                line[x] = (line[x] + line[x - 4]) & 255
        elif filt == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif filt == 3:
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                line[x] = (line[x] + (a + prev[x]) // 2) & 255
        elif filt == 4:
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                b = prev[x]
                c = prev[x - 4] if x >= 4 else 0
                pa_, pb_, pc_ = a + b - c, a, b
                pr = (pa_ if (abs(pa_ - a) <= abs(pb_ - a) and abs(pa_ - a) <= abs(pc_ - a))
                      else (b if abs(pb_ - a) <= abs(pc_ - a) else c))
                line[x] = (line[x] + pr) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, bytes(out)


def encode_png(w, h, px):
    def chunk(typ_, data):
        c = struct.pack(">I", len(data)) + typ_ + data
        return c + struct.pack(">I", zlib.crc32(typ_ + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + px[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def compose(w, h, px):
    px = bytearray(px)
    bh = max(2, round(h * 0.22))          # Bannerhoehe
    th = bh * 0.62                        # Schrifthoehe
    total = sum(GLYPHS[c][0] for c in "LITE") + GAP * 3
    x0 = (w - total * th) / 2
    for y in range(h - bh, h):
        row = y * w * 4
        for x in range(w):
            i = row + x * 4
            px[i] = int(0.95 * TURQ[0] + 0.05 * px[i])
            px[i + 1] = int(0.95 * TURQ[1] + 0.05 * px[i + 1])
            px[i + 2] = int(0.95 * TURQ[2] + 0.05 * px[i + 2])
            px[i + 3] = 255
    cx, ty = x0, h - bh + (bh - th) / 2
    for ch in "LITE":
        gw, rects = GLYPHS[ch]
        for (rx, ry, rw, rh) in rects:
            xa = int(round(cx + rx * th)); xb = int(round(cx + (rx + rw) * th))
            ya = int(round(ty + ry * th)); yb = int(round(ty + (ry + rh) * th))
            for yy in range(max(0, ya), min(h, yb)):
                base = yy * w * 4
                for xx in range(max(0, xa), min(w, xb)):
                    i = base + xx * 4
                    px[i], px[i + 1], px[i + 2], px[i + 3] = INK[0], INK[1], INK[2], 255
        cx += (gw + GAP) * th
    return px


def main():
    src = SRC.read_bytes()
    res, typ, cnt = struct.unpack("<HHH", src[:6])
    assert res == 0 and typ == 1 and cnt > 0, "keine gueltige ICO-Datei"
    entries = []
    for i in range(cnt):
        off = 6 + i * 16
        w, h, c, r, planes, bpp, size, dataoff = struct.unpack("<BBBBHHII", src[off:off + 16])
        entries.append((256 if w == 0 else w, size, dataoff))
    result = []
    for size, dsize, doff in sorted(entries):
        w, h, px = decode_png(src[doff:doff + dsize])
        assert (w, h) == (size, size), (w, h, size)
        result.append((size, encode_png(w, h, bytes(compose(w, h, px)))))
    header = struct.pack("<HHH", 0, 1, len(result))
    dirtab, payload, offset = b"", b"", 6 + 16 * len(result)
    for size, png in sorted(result):
        b = 0 if size >= 256 else size
        dirtab += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        payload += png
    DST.write_bytes(header + dirtab + payload)
    # Selbstverifikation: Banner in jeder Groesse nachweisbar
    d = DST.read_bytes()
    _, _, n = struct.unpack("<HHH", d[:6])
    for i in range(n):
        off = 6 + i * 16
        w, h, c, r, planes, bpp, size, dataoff = struct.unpack("<BBBBHHII", d[off:off + 16])
        rw = 256 if w == 0 else w
        ww, hh, px = decode_png(d[dataoff:dataoff + size])
        assert (ww, hh) == (rw, rw)
        bh = max(2, round(rw * 0.22))
        band = px[(rw - bh) * rw * 4:]
        turq = sum(1 for i4 in range(0, len(band), 4)
                   if band[i4] < 60 and band[i4 + 1] > 150 and band[i4 + 2] > 150)
        assert turq > 0, f"Banner fehlt in Groesse {rw}"
    print(f"OK: {DST} ({len(d)} Bytes, {n} Groessen) mit LITE-Banner")


if __name__ == "__main__":
    main()
