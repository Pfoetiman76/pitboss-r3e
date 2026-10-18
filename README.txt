PitBoss R3E 0.1.0 Beta
======================

Eigenstaendige Telemetrie-/Coaching-App fuer RaceRoom Racing Experience.
Liest den Shared-Memory-Block $R3E (Sector3 r3e.h v3.5) - ohne Plugin, ohne Zusatzsoftware.

Start
-----
1. RaceRoom starten und in eine Session gehen (Training/Quali/Rennen).
2. PitBoss R3E starten (Installer oder "python main.py" / Start-App.bat).
3. Oben steht "RaceRoom verbunden", sobald Daten fliessen.

Funktionen
----------
- Live-Overlays: Reifen (Temp/Druck/Verschleiss/Flatspot mit den Fenstern des Spiels), Bremsen,
  Pedale/Lenkung, Delta, Sektoren, Pit-Fenster/Standzeit, Fahrzeugschaden, Flaggen,
  Spotter/Ueberholalarm, Gegnerabstaende
- Recording pro Session (CSV), Rundenanalyse, saubere Runden, Referenzrunde (Export/Import)
- Input-Coach, Limit-Coach, Fahrer-/Hardwareprofil, KI-Coach (Gemini, optional), Sprachausgabe (Piper/SAPI)
- Reports und CSV unter Dokumente\PitBoss R3E\

Kalibrierung (einmalig, falls Werte seltsam aussehen)
-----------------------------------------------------
    python raceroom_sm.py --probe
in einer laufenden Session ausfuehren und die Ausgabe pruefen. Falls die automatische
Erkennung falsch liegt, per Umgebungsvariable setzen:
    PITBOSS_R3E_WEAR=new1|new0           Reifenverschleiss: 1.0 = neu | 0.0 = neu
    PITBOSS_R3E_SECTORS=cumulative|single  Sektorzeiten kumulativ | einzeln
    PITBOSS_R3E_DAMAGE=intact1|intact0   Fahrzeugschaden: 1.0 = heil | 0.0 = heil

Nicht verfuegbar in RaceRoom (daher nicht enthalten)
----------------------------------------------------
Wetter-/Streckenzustand, Reifenkarkassen-Temperatur, Setup-Datei-Import, Lift&Coast-Schaetzung,
Referenzzeiten-Datenbank. Unbekannte Werte werden als 0 bzw. -1 gefuehrt, nicht geraten.

Versionen
---------
0.1.0 Beta  Erste eigenstaendige RaceRoom-Version (Fork von PitBoss 0.5.9.31, LMU-Code entfernt).
