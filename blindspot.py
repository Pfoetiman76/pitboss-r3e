# -*- coding: utf-8 -*-
"""
PitBoss R3E - Toter-Winkel-Erkennung (Blind Spot)
==================================================
Reine, seiteneffektfreie Berechnung (kein PySide6, keine Shared Memory) -
absichtlich so gehalten, damit sie per Selftest (test_blindspot.py) gegen
synthetische Gegnerpositionen geprueft werden kann.

Koordinatensystem (R3E shared memory, Bodenebene):
  - Positionen in Metern, 2D (x, y) auf der Streckenebene.
  - own_heading_deg: Fahrtrichtung des eigenen Autos. Konvention hier:
    0 Grad = +x-Achse, Drehung gegen den Uhrzeigersinn (mathematisch positiv).
    (Integration in raceroom_sm.py: dort wird beim Anbinden ein eventueller
    Achs-Offset einmalig korrigiert - siehe normalize_heading() am Ende.)

Konzept:
  Fuer jeden Gegner wird der Vektor zum eigenen Auto ins eigene Fahrzeug-
  Koordinatensystem gedreht:
    f = Anteil in Fahrtrichtung ("nach vorn"),
    l = Anteil quer dazu, positiv = rechts.
  Der Peerabstandswinkel (bearing) ist der Winkel zwischen Fahrtrichtung und
  Vektor zum Gegner. Liegt er im Hecksektor (Standard 120..240 Grad) und der
  Querabstand im Fenster (Standard 1.0..6.0 m) und die Gesamtentfernung unter
  dem Limit (Standard 15 m), gilt der Gegner als im toten Winkel.
  Der Zaehler steht dann fuer die Seite (l > 0 = rechts, l < 0 = links).
"""

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlindSpotConfig:
    """Schwellen der Toter-Winkel-Erkennung (alle konfigurierbar)."""
    bearing_min_deg: float = 120.0   # Hecksektor ab (ab Fahrtrichtung, im Uhrzeigersinn rechts)
    bearing_max_deg: float = 240.0   # Hecksektor bis
    lateral_min_m: float = 1.0        # kleinerer Querabstand = direkt dahinter, kein toter Winkel
    lateral_max_m: float = 6.0        # groeserer Querabstand = klar getrennt
    max_distance_m: float = 15.0      # Gesamtentfernung, ab der ignoriert wird
    critical_distance_m: float = 3.0  # ab hier wird die Kachel rot statt amber


DEFAULT_CONFIG = BlindSpotConfig()


# ---------------------------------------------------------------------------
# Kernberechnung
# ---------------------------------------------------------------------------

def own_frame(own_x: float, own_y: float, own_heading_deg: float,
              opp_x: float, opp_y: float):
    """Vektor zum Gegner im eigenen Fahrzeugrahmen.

    Rueckgabe (f, l):
      f > 0: Gegner vor dem eigenen Auto; f < 0: dahinter.
      l > 0: Gegner rechts; l < 0: links.
    """
    dx = opp_x - own_x
    dy = opp_y - own_y
    phi = math.radians(own_heading_deg)
    # Einheitsvektor Fahrtrichtung
    fwd_x, fwd_y = math.cos(phi), math.sin(phi)
    # Einheitsvektor "rechts" = Fahrtrichtung um -90 Grad gedreht
    right_x, right_y = math.sin(phi), -math.cos(phi)
    f = dx * fwd_x + dy * fwd_y
    l = dx * right_x + dy * right_y
    return f, l


def bearing_deg(f: float, l: float) -> float:
    """Winkel zwischen Fahrtrichtung und Gegnerrichtung, 0..360 Grad.

    0 = genau vorn, 90 = rechts, 180 = genau hinten, 270 = links.
    """
    ang = math.degrees(math.atan2(l, f))
    return ang % 360.0


def classify_opponent(own_x: float, own_y: float, own_heading_deg: float,
                      opp_x: float, opp_y: float,
                      cfg: BlindSpotConfig = DEFAULT_CONFIG):
    """Bewertet EINEN Gegner. Rueckgabe dict:

      active    - im toten Winkel ja/nein
      side      - 'left' / 'right' / None
      distance_m- euklidische Entfernung (immer gesetzt)
      lateral_m - Querabstand mit Vorzeichen (rechts positiv)
      forward_m - Laengsabstand mit Vorzeichen (vorn positiv)
      bearing   - Peerabstandswinkel 0..360
      critical  - Entfernung <= cfg.critical_distance_m
    """
    f, l = own_frame(own_x, own_y, own_heading_deg, opp_x, opp_y)
    dist = math.hypot(f, l)
    brg = bearing_deg(f, l)
    active = (
        cfg.bearing_min_deg <= brg <= cfg.bearing_max_deg
        and cfg.lateral_min_m <= abs(l) <= cfg.lateral_max_m
        and dist <= cfg.max_distance_m
    )
    side = None
    if active:
        side = "right" if l > 0 else "left"
    return {
        "active": active,
        "side": side,
        "distance_m": round(dist, 2),
        "lateral_m": round(l, 2),
        "forward_m": round(f, 2),
        "bearing": round(brg, 1),
        "critical": dist <= cfg.critical_distance_m,
    }


def blindspot_status(own_x: float, own_y: float, own_heading_deg: float,
                     opponents, cfg: BlindSpotConfig = DEFAULT_CONFIG) -> dict:
    """Gesamtstatus fuer die VR-Tafel und das Desktop-Overlay.

    opponents: iterierbar von (x, y)-Tupeln (Gegnerpositionen).
    Rueckgabe:
      {"left":  {"active": bool, "distance_m": float|None, "critical": bool},
       "right": {...},
       "any": bool}
    Pro Seite zaehlt der naechste aktive Gegner (kleinste Entfernung).
    """
    best = {"left": None, "right": None}
    for opp in opponents:
        ox, oy = opp[0], opp[1]
        c = classify_opponent(own_x, own_y, own_heading_deg, ox, oy, cfg)
        if not c["active"]:
            continue
        side = c["side"]
        if best[side] is None or c["distance_m"] < best[side]["distance_m"]:
            best[side] = {
                "distance_m": c["distance_m"],
                "critical": c["critical"],
            }
    def pack(side):
        if best[side] is None:
            return {"active": False, "distance_m": None, "critical": False}
        return {
            "active": True,
            "distance_m": best[side]["distance_m"],
            "critical": best[side]["critical"],
        }
    left, right = pack("left"), pack("right")
    return {"left": left, "right": right,
            "any": left["active"] or right["active"]}


# ---------------------------------------------------------------------------
# Integrationshelf (wird von main.py genutzt, sobald 0.4.0.0 integriert wird)
# ---------------------------------------------------------------------------

def normalize_heading(heading_deg: float, axis_offset_deg: float = 0.0) -> float:
    """Bringt einen Heading-Wert (inkl. optionalem Achs-Offset des Spiels)
    in die Konvention 0..360, 0 Grad = +x, gegen den Uhrzeigersinn positiv."""
    return (heading_deg + axis_offset_deg) % 360.0
