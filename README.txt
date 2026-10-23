PitBoss R3E 0.1.5 Beta
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
0.1.5 Beta  Spiel-Stoerung behoben: Shared Memory wird nur noch geoeffnet (nie angelegt), Overlays nehmen dem Spiel nie den Fokus.
0.1.4 Beta  API-Pruefung gegen r3e.h 3.5 (Stand 03/2026, nach RaceRoom-Update 21.10.2026 unveraendert): Layout-/Versionswaechter mit Hinweis im Verbindungs-Feld.
0.1.3 Beta  Logo: PitBoss + RaceRoom kombiniert (Header und App-Icon).
0.1.2 Beta  Reifen-Overlay ein Viertel kleiner; Kurven-Coach erkennt auch leichtere Bremszonen (alle Kurven mit relevantem Tempoabbau).
0.1.1 Beta  Reifen-Overlay: Farben nach Temperaturfenster, Carc entfernt; Live-Coach fuer langsame Autos/kurze Strecken; RaceRoom-Logo; Menue Mehr aufgeraeumt; automatische Update-Pruefung beim Start.
0.1.0 Beta  Erste eigenstaendige RaceRoom-Version (Fork von PitBoss 0.5.9.31, LMU-Code entfernt).
