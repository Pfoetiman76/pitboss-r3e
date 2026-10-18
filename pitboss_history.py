"""
PitBoss — Rundenzeiten-Verlauf  (additiv, 0.5.9.24)
=========================================================================
Liest alle bereits vorhandenen Session-CSVs aus dem PitBoss-R3E-Export-Ordner
(Dokumente\\PitBoss R3E\\csv\\r3e_live_recorder_samples_*.csv), fasst sie pro
Session zu Rundenzeiten zusammen und baut daraus:

  - eine lesbare Konsolen-/Text-Übersicht (neueste Session zuerst)
  - lap_history_summary.csv   (eine Zeile pro erkannter Runde, alle Sessions)
  - personal_bests.csv        (schnellste gültige Runde je Strecke+Fahrzeug)

Rein additiv: liest nur, verändert/löscht keine PitBoss-Dateien. Standalone,
keine Abhängigkeiten außerhalb der Python-Standardbibliothek.

Nutzung (auf dem PC, auf dem auch PitBoss läuft/lief):
    python pitboss_history.py
    python pitboss_history.py --csv-dir "D:\\Custom\\Pfad\\csv"
    python pitboss_history.py --track Spa --vehicle Ginetta
    python pitboss_history.py --selftest
"""

from __future__ import annotations
import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Pfade — dieselbe Logik wie in main.py (_default_data_dir), damit das Tool
# ohne Parameter direkt im richtigen Ordner sucht.
# ---------------------------------------------------------------------------
def default_data_dir() -> Path:
    try:
        home = Path.home()
        docs = home / "Documents"
        return (docs if docs.is_dir() else home) / "PitBoss R3E"
    except Exception:
        return Path.cwd() / "PitBoss R3E"


# Plausibilitätsgrenzen für eine echte Rundenzeit (Sekunden). Filtert
# Reset-/Mess-Artefakte (0, negative, riesige Werte durch Session-Wechsel).
MIN_LAP_S = 15.0
MAX_LAP_S = 900.0


@dataclass
class LapRecord:
    session_file: str
    session_stamp: str
    track: str
    vehicle: str
    lap_number: int
    lap_time_s: float
    valid: bool          # nicht invalidiert, nicht in der Box gewesen
    reason: str


@dataclass
class SessionSummary:
    file: Path
    stamp: str
    track: str
    vehicle: str
    total_rows: int
    laps: List[LapRecord] = field(default_factory=list)

    @property
    def valid_laps(self) -> List[LapRecord]:
        return [l for l in self.laps if l.valid]

    @property
    def best_lap(self) -> Optional[LapRecord]:
        vl = self.valid_laps
        return min(vl, key=lambda l: l.lap_time_s) if vl else None


def fmt_lap_time(seconds: float) -> str:
    if seconds is None or seconds <= 0:
        return "--:--.---"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:06.3f}"


def _most_common(values: List[str]) -> str:
    vals = [v for v in values if v]
    if not vals:
        return "unbekannt"
    return Counter(vals).most_common(1)[0][0]


def parse_session_csv(path: Path) -> Optional[SessionSummary]:
    """Liest eine einzelne r3e_live_recorder_samples_*.csv und leitet daraus
    pro Runde die offizielle Rundenzeit ab (last_lap_time der jeweils
    NÄCHSTEN Runde — genau wie main.py das beim Live-Recording selbst tut)."""
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None
    if not rows:
        return None

    by_lap: Dict[int, list] = defaultdict(list)
    for r in rows:
        try:
            lap = int(float(r.get("lap_number", -1)))
        except Exception:
            continue
        if lap <= 0:
            continue
        by_lap[lap].append(r)

    if not by_lap:
        return None

    track = _most_common([r.get("track", "") for r in rows])
    vehicle = _most_common(
        [r.get("vehicle_model", "") or r.get("vehicle_name", "") for r in rows]
    )
    stamp = path.stem.replace("r3e_live_recorder_samples_", "")

    summary = SessionSummary(file=path, stamp=stamp, track=track, vehicle=vehicle, total_rows=len(rows))

    for lap_no in sorted(by_lap):
        this_lap_rows = by_lap[lap_no]
        next_lap_rows = by_lap.get(lap_no + 1, [])

        # Offizielle Zeit: last_lap_time, gemeldet sobald die NÄCHSTE Runde begonnen hat.
        candidates = []
        for r in next_lap_rows:
            try:
                v = float(r.get("last_lap_time", 0.0))
            except Exception:
                v = 0.0
            if MIN_LAP_S <= v <= MAX_LAP_S:
                candidates.append(round(v, 3))
        if candidates:
            lap_time = Counter(candidates).most_common(1)[0][0]
        else:
            # Fallback: manchmal steht der Wert schon in den letzten Samples
            # derselben Runde (Sim meldet ihn kurz vor dem Linienwechsel).
            fallback = []
            for r in this_lap_rows:
                try:
                    v = float(r.get("last_lap_time", 0.0))
                except Exception:
                    v = 0.0
                if MIN_LAP_S <= v <= MAX_LAP_S:
                    fallback.append(round(v, 3))
            lap_time = Counter(fallback).most_common(1)[0][0] if fallback else 0.0

        invalidated = any(int(float(r.get("lap_invalidated", 0) or 0)) for r in this_lap_rows)
        in_pits = any(int(float(r.get("in_pits", 0) or 0)) for r in this_lap_rows)

        if lap_time <= 0:
            valid, reason = False, "keine Zeit ermittelbar"
        elif invalidated:
            valid, reason = False, "invalidiert"
        elif in_pits:
            valid, reason = False, "Pit"
        else:
            valid, reason = True, "gültig"

        summary.laps.append(LapRecord(
            session_file=path.name, session_stamp=stamp, track=track, vehicle=vehicle,
            lap_number=lap_no, lap_time_s=lap_time, valid=valid, reason=reason,
        ))

    return summary


def collect_sessions(csv_dir: Path) -> List[SessionSummary]:
    files = sorted(csv_dir.glob("r3e_live_recorder_samples_*.csv"))
    sessions = []
    for f in files:
        s = parse_session_csv(f)
        if s is not None:
            sessions.append(s)
    # neueste zuerst (Dateiname trägt den Zeitstempel)
    sessions.sort(key=lambda s: s.stamp, reverse=True)
    return sessions


def filter_sessions(sessions: List[SessionSummary], track: Optional[str], vehicle: Optional[str]) -> List[SessionSummary]:
    out = sessions
    if track:
        t = track.lower()
        out = [s for s in out if t in s.track.lower()]
    if vehicle:
        v = vehicle.lower()
        out = [s for s in out if v in s.vehicle.lower()]
    return out


def print_overview(sessions: List[SessionSummary]) -> None:
    if not sessions:
        print("Keine passenden Session-CSVs gefunden.")
        return
    for s in sessions:
        valid = s.valid_laps
        print(f"\n{s.stamp}  |  {s.track}  |  {s.vehicle}  |  {s.file.name}")
        print(f"  Runden erkannt: {len(s.laps)}  |  davon gültig: {len(valid)}  |  Samples: {s.total_rows}")
        if valid:
            best = s.best_lap
            times = [l.lap_time_s for l in valid]
            print(f"  Beste Runde:  Lap {best.lap_number} | {fmt_lap_time(best.lap_time_s)}")
            print(f"  Schnitt gültig: {fmt_lap_time(statistics.mean(times))}  |  Median: {fmt_lap_time(statistics.median(times))}")
        else:
            print("  Keine gültige Runde in dieser Session.")


def print_personal_bests(sessions: List[SessionSummary]) -> None:
    best: Dict[tuple, LapRecord] = {}
    for s in sessions:
        for lap in s.valid_laps:
            key = (lap.track, lap.vehicle)
            if key not in best or lap.lap_time_s < best[key].lap_time_s:
                best[key] = lap
    if not best:
        print("\nKeine Bestzeiten (keine gültigen Runden gefunden).")
        return
    print("\nPersönliche Bestzeiten je Strecke/Fahrzeug:")
    for (track, vehicle), lap in sorted(best.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        print(f"  {track:<30} {vehicle:<30} {fmt_lap_time(lap.lap_time_s)}  (Session {lap.session_stamp}, Lap {lap.lap_number})")


def write_lap_history_csv(sessions: List[SessionSummary], out_path: Path) -> int:
    rows = []
    for s in sessions:
        for lap in s.laps:
            rows.append(lap)
    rows.sort(key=lambda l: (l.session_stamp, l.lap_number))
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["session_stamp", "session_file", "track", "vehicle", "lap_number", "lap_time_s", "lap_time", "valid", "reason"])
        for l in rows:
            w.writerow([l.session_stamp, l.session_file, l.track, l.vehicle, l.lap_number,
                        f"{l.lap_time_s:.3f}", fmt_lap_time(l.lap_time_s), int(l.valid), l.reason])
    return len(rows)


def write_personal_bests_csv(sessions: List[SessionSummary], out_path: Path) -> int:
    best: Dict[tuple, LapRecord] = {}
    for s in sessions:
        for lap in s.valid_laps:
            key = (lap.track, lap.vehicle)
            if key not in best or lap.lap_time_s < best[key].lap_time_s:
                best[key] = lap
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["track", "vehicle", "best_lap_time_s", "best_lap_time", "session_stamp", "lap_number"])
        for (track, vehicle), lap in sorted(best.items()):
            w.writerow([track, vehicle, f"{lap.lap_time_s:.3f}", fmt_lap_time(lap.lap_time_s), lap.session_stamp, lap.lap_number])
    return len(best)


# ---------------------------------------------------------------------------
# Selbsttest — baut Mock-CSVs im exakten write_csv-Schema (nur die für die
# Auswertung relevanten Spalten sind gefüllt) und prüft die Rundenlogik.
# ---------------------------------------------------------------------------
def _run_selftest() -> int:
    import tempfile

    HEADER = ["timestamp", "track", "vehicle_model", "vehicle_name", "lap_number",
              "last_lap_time", "lap_invalidated", "in_pits"]

    def row(track, vehicle, lap, last_lap_time, invalidated=0, in_pits=0):
        return {"timestamp": "t", "track": track, "vehicle_model": vehicle, "vehicle_name": vehicle,
                "lap_number": lap, "last_lap_time": last_lap_time, "lap_invalidated": invalidated, "in_pits": in_pits}

    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "r3e_live_recorder_samples_20260101_120000.csv"
        rows = []
        # Lap 1 (Outlap, keine Zeit) -> Lap 2 beginnt, last_lap_time für Lap 1 kommt hier rein
        for _ in range(5):
            rows.append(row("Spa", "GinettaTest", 1, 0.0))
        for _ in range(5):
            rows.append(row("Spa", "GinettaTest", 2, 91.209))  # offizielle Zeit für Lap 1
        for _ in range(5):
            rows.append(row("Spa", "GinettaTest", 3, 89.5))    # offizielle Zeit für Lap 2 (Bestzeit)
        # Lap 3 wird in der Box beendet -> ungültig
        for _ in range(3):
            rows.append(row("Spa", "GinettaTest", 4, 999.0, in_pits=1))

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            for r in rows:
                w.writerow(r)

        s = parse_session_csv(csv_path)
        if s is None:
            failures.append("parse_session_csv lieferte None")
        else:
            laps = {l.lap_number: l for l in s.laps}
            if 1 not in laps or abs(laps[1].lap_time_s - 91.209) > 0.001 or not laps[1].valid:
                failures.append(f"Lap 1 falsch erkannt: {laps.get(1)}")
            if 2 not in laps or abs(laps[2].lap_time_s - 89.5) > 0.001 or not laps[2].valid:
                failures.append(f"Lap 2 falsch erkannt: {laps.get(2)}")
            best = s.best_lap
            if best is None or best.lap_number != 2:
                failures.append(f"Bestzeit falsch: {best}")
            if s.track != "Spa" or s.vehicle != "GinettaTest":
                failures.append(f"Track/Vehicle falsch erkannt: {s.track} / {s.vehicle}")

        sessions = collect_sessions(tmp_path)
        if len(sessions) != 1:
            failures.append(f"collect_sessions fand {len(sessions)} statt 1 Session")

        out_csv = tmp_path / "lap_history_summary.csv"
        n = write_lap_history_csv(sessions, out_csv)
        if n != 4 or not out_csv.exists():
            failures.append(f"write_lap_history_csv: {n} Zeilen statt 4 oder Datei fehlt")

        pb_csv = tmp_path / "personal_bests.csv"
        n_pb = write_personal_bests_csv(sessions, pb_csv)
        if n_pb != 1 or not pb_csv.exists():
            failures.append(f"write_personal_bests_csv: {n_pb} Einträge statt 1 oder Datei fehlt")

        # Filter-Test
        filtered = filter_sessions(sessions, track="spa", vehicle=None)
        if len(filtered) != 1:
            failures.append("filter_sessions (Track) fehlgeschlagen")
        filtered_none = filter_sessions(sessions, track="Nürburgring", vehicle=None)
        if len(filtered_none) != 0:
            failures.append("filter_sessions (Track, kein Treffer) fehlgeschlagen")

    if failures:
        print(f"SELFTEST FEHLGESCHLAGEN ({len(failures)}):")
        for f_ in failures:
            print(f"  - {f_}")
        return 1
    print("Selftest OK (7/7 Prüfungen).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="PitBoss Rundenzeiten-Verlauf aus vorhandenen Session-CSVs")
    ap.add_argument("--csv-dir", type=str, default=None, help="Ordner mit r3e_live_recorder_samples_*.csv (Default: Dokumente\\PitBoss R3E\\csv)")
    ap.add_argument("--out-dir", type=str, default=None, help="Ordner für die zusammengefassten CSVs (Default: wie --csv-dir/..)")
    ap.add_argument("--track", type=str, default=None, help="Nur Sessions filtern, deren Strecke diesen Text enthält")
    ap.add_argument("--vehicle", type=str, default=None, help="Nur Sessions filtern, deren Fahrzeug diesen Text enthält")
    ap.add_argument("--no-write", action="store_true", help="Nur Konsolen-Ausgabe, keine CSV-Dateien schreiben")
    ap.add_argument("--selftest", action="store_true", help="Mock-Daten testen und beenden")
    args = ap.parse_args()

    if args.selftest:
        return _run_selftest()

    csv_dir = Path(args.csv_dir) if args.csv_dir else (default_data_dir() / "csv")
    if not csv_dir.is_dir():
        print(f"CSV-Ordner nicht gefunden: {csv_dir}")
        print("Hinweis: --csv-dir <Pfad> angeben, falls PitBoss woanders speichert.")
        return 1

    sessions = collect_sessions(csv_dir)
    sessions = filter_sessions(sessions, args.track, args.vehicle)

    print(f"Gefundene Sessions: {len(sessions)}  (Quelle: {csv_dir})")
    print_overview(sessions)
    print_personal_bests(sessions)

    if not args.no_write and sessions:
        out_dir = Path(args.out_dir) if args.out_dir else csv_dir.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        n1 = write_lap_history_csv(sessions, out_dir / "lap_history_summary.csv")
        n2 = write_personal_bests_csv(sessions, out_dir / "personal_bests.csv")
        print(f"\nGeschrieben: lap_history_summary.csv ({n1} Runden), personal_bests.csv ({n2} Bestzeiten) in {out_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
