# -*- coding: utf-8 -*-
"""Selftest fuer blindspot.py: synthetische Gegnerpositionen.

Aufruf:  python test_blindspot.py   -> PASS/FAIL pro Fall, Exit-Code 0/1.
"""

import sys
from blindspot import (BlindSpotConfig, classify_opponent, blindspot_status,
                       own_frame, bearing_deg, normalize_heading)

CASES = []


def case(name, fn):
    CASES.append((name, fn))


# Eigene Referenzposition: (0, 0), Heading 0 Grad = Richtung +x.

# --- Grundfaellen -----------------------------------------------------------
case("Gegner direkt dahinter ist KEIN toter Winkel",
     lambda: not classify_opponent(0, 0, 0, -5, 0)["active"])

case("Gegner rechts-hinten ist rechter toter Winkel",
     lambda: classify_opponent(0, 0, 0, -5, 2.5)["side"] == "right"
             and classify_opponent(0, 0, 0, -5, 2.5)["active"])

case("Gegner links-hinten ist linker toter Winkel",
     lambda: classify_opponent(0, 0, 0, -5, -2.5)["side"] == "left")

case("Gegner quer knapp daneben (bearing ca. 90/270) ist frei",
     lambda: not classify_opponent(0, 0, 0, 0, 3)["active"]
             and not classify_opponent(0, 0, 0, 0, -3)["active"])

case("Gegner schraeg vorne ist frei",
     lambda: not classify_opponent(0, 0, 0, 5, 3)["active"])

case("Grenzfall: bearing exakt 120 Grad ist aktiv (inklusive Untergrenze)",
     lambda: classify_opponent(0, 0, 0, -3.0, 5.196)["active"])

case("Grenzfall: bearing knapp unter 120 Grad ist frei",
     lambda: not classify_opponent(0, 0, 0, -3.2, 5.196)["active"])

case("Querabstand unter lateral_min (0.5 m) ist frei",
     lambda: not classify_opponent(0, 0, 0, -5, 0.5)["active"])

case("Querabstand ueber lateral_max (6.5 m) ist frei",
     lambda: not classify_opponent(0, 0, 0, -5, 6.5)["active"])

case("Entfernung ueber 15 m ist frei",
     lambda: not classify_opponent(0, 0, 0, -14.5, 4.0)["active"])

case("Kritische Naehe (2 m) wird als critical markiert",
     lambda: classify_opponent(0, 0, 0, -1.5, 1.3)["critical"])

case("Entfernung wird korrekt berechnet (3-4-5)",
     lambda: abs(classify_opponent(0, 0, 0, -3, 4)["distance_m"] - 5.0) < 1e-6)

# --- Heading-Drehungen ------------------------------------------------------
case("Heading 90 Grad: 'hinten' liegt jetzt Richtung -y",
     lambda: classify_opponent(0, 0, 90, 0, -5, )["active"] is False
             and classify_opponent(0, 0, 90, -2.5, -5)["side"] == "right")

case("Heading 180 Grad: Gegner bei +x liegt hinter uns",
     lambda: classify_opponent(0, 0, 180, 5, 2.5)["side"] == "right")

case("Heading 270 Grad: links/rechts bleibt vertauschungsfrei",
     lambda: classify_opponent(0, 0, 270, 2.5, 5)["side"] == "left")

# --- Gesamtstatus -----------------------------------------------------------
case("Status ohne Gegner: beide Seiten frei",
     lambda: blindspot_status(0, 0, 0, [])["any"] is False)

case("Status mit einem linken Gegner",
     lambda: (lambda s: s["left"]["active"] and not s["right"]["active"]
              and abs(s["left"]["distance_m"] - 5.0) < 1e-6)
             (blindspot_status(0, 0, 0, [(-4.0, -3.0)])))

case("Status: naechster Gegner gewinnt (links 4 m vs 10 m)",
     lambda: abs(blindspot_status(0, 0, 0, [(-9.0, -4.0), (-3.0, -2.5)])
                 ["left"]["distance_m"] - 3.9) < 0.2)

case("Status: beide Seiten gleichzeitig belegt",
     lambda: (lambda s: s["left"]["active"] and s["right"]["active"])
             (blindspot_status(0, 0, 0, [(-5, -2.5), (-5, 2.5)])))

case("Status: Gegner vor dem Auto beeinflusst nichts",
     lambda: not blindspot_status(0, 0, 0, [(10, 2)])["any"])

# --- Konfigurierbarkeit -----------------------------------------------------
case("Engere Schwellen (max 10 m) sortieren Weitweg-Gegner aus",
     lambda: not classify_opponent(0, 0, 0, -9.0, 4.0,
                                   BlindSpotConfig(max_distance_m=10.0))["active"]
             and classify_opponent(0, 0, 0, -4.0, 3.0,
                                   BlindSpotConfig(max_distance_m=10.0))["active"])

# --- Helfer -----------------------------------------------------------------
case("bearing_deg: vorn=0, rechts=90, hinten=180, links=270",
     lambda: bearing_deg(1, 0) == 0 and abs(bearing_deg(0, 1) - 90) < 1e-6
             and abs(bearing_deg(-1, 0) - 180) < 1e-6
             and abs(bearing_deg(0, -1) - 270) < 1e-6)

case("own_frame Vorzeichen: l positiv = rechts",
     lambda: own_frame(0, 0, 0, 1, 1)[1] > 0)

case("normalize_heading: 370 -> 10, -90 -> 270, mit Offset",
     lambda: abs(normalize_heading(370) - 10) < 1e-9
             and abs(normalize_heading(-90) - 270) < 1e-9
             and abs(normalize_heading(350, 20) - 10) < 1e-9)


def main():
    failures = []
    for name, fn in CASES:
        try:
            ok = bool(fn())
        except Exception as exc:  # noqa: BLE001 - Selftest soll alles fangen
            ok = False
            name = name + f" [Ausnahme: {exc!r}]"
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures.append(name)
        print(f"[{status}] {name}")
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} Faelle bestanden.")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
