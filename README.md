# PitBoss R3E

Eigenstaendige Telemetrie- und Coaching-App fuer **RaceRoom Racing Experience** (Windows, PySide6).
Liest den Shared Memory `$R3E` (Sector3 `r3e.h` v3.5) direkt - kein Plugin noetig.

- Live-Overlays (Reifen, Bremsen, Pedale, Delta, Sektoren, Pit, Schaden, Flaggen, Spotter, Ueberholalarm)
- Recording, Rundenanalyse, Referenzrunden, Input-/Limit-Coach, Live-Coach (lokal, optional mit KI-Anbieter: ChatGPT, Mistral, Gemini, Claude, DeepSeek) und Sprachausgabe
- Installer + Auto-Update ueber GitHub Releases

## Entwicklung
```
pip install PySide6 pywin32
python main.py
python raceroom_sm.py --selftest   # Mapping-Tests
python raceroom_sm.py --probe      # Rohwerte aus laufender Session (Kalibrierung)
```
Details: `README.txt`, Release-Ablauf: `RELEASING.md`.
