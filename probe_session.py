"""PitBoss R3E - Probe-Sammler (0.2.4 Kalibrierung, Issue #2).

Laesst raceroom_sm.py --probe nicht nur einmal, sondern wiederholt laufen
und schreibt alle Snapshots mit Zeitstempel in eine Datei. Damit lassen sich
Verschleiss-Richtung (1.0=neu?), Sektorzeit-Modus (kumulativ/einzeln) und
Schadens-Richtung (1.0=heil?) waehrend einer echten Session kalibrieren.

Aufruf:
    python probe_session.py            # Standard: alle 30 s, bis Strg+C
    python probe_session.py 15         # alle 15 s
Ergebnis: probe_session_JJJJMMTT_HHMMSS.txt neben dem Skript.
Danach die Datei an PitBoss/Vibe hochladen zur Kalibrierung.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

import raceroom_sm


def main() -> int:
    interval = 30.0
    for a in sys.argv[1:]:
        try:
            v = float(a)
            if v > 0:
                interval = min(v, 300.0)
        except ValueError:
            pass

    out_path = Path(__file__).resolve().parent / f"probe_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    rd = raceroom_sm.R3EReader(raceroom_sm._FakeSample)
    n = 0

    print("PitBoss R3E Probe-Sammler")
    print(f"Intervall: {interval:.0f} s | Ausgabe: {out_path}")
    print("Warte auf RaceRoom und eine laufende Session ... (Strg+C beendet)")

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"PitBoss R3E Probe-Sammler | Intervall {interval:.0f} s | Start {datetime.now().isoformat(timespec='seconds')}
")
        try:
            while True:
                stamp = datetime.now().isoformat(timespec="seconds")
                try:
                    d = rd.read_object()
                    if int(d.version_major) != raceroom_sm.R3E_VERSION_MAJOR:
                        fh.write(f"\n===== {stamp} =====\n[wartet] $R3E inaktiv (version_major={int(d.version_major)})\n")
                        print(f"\r[{stamp}] wartet: Spiel/Session nicht aktiv", end="", flush=True)
                    else:
                        try:
                            rd.read_sample()  # Heuristiken (Verschleiss/Sektoren/Schaden) aktualisieren
                        except Exception:
                            pass
                        block = raceroom_sm._probe_text(rd, d)
                        fh.write(f"\n===== {stamp} (Probe #{n + 1}) =====\n{block}\n")
                        fh.flush()
                        n += 1
                        print(f"\r[{stamp}] Probe #{n} aufgezeichnet", end="", flush=True)
                except Exception as e:
                    fh.write(f"\n===== {stamp} =====\n[wartet] {e}\n")
                    print(f"\r[{stamp}] wartet: {str(e)[:70]}", end="", flush=True)
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            fh.write(f"\nEnde {datetime.now().isoformat(timespec='seconds')} | Probes: {n}\n")
    print(f"\n\nFertig. {n} Snapshots gespeichert in:\n{out_path}")
    print("Diese Datei fuer die Kalibrierung an Vibe/PitBoss hochladen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
