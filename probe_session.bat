@echo off
rem PitBoss R3E - Probe-Sammler: Doppelklick waehrend einer RaceRoom-Session.
rem Alle 30 s ein Kalibrier-Snapshot, Strg+C beendet. Ausgabe: probe_session_*.txt
cd /d "%~dp0"
python probe_session.py
pause
