PitBoss R3E 0.2.3 Beta
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
- Input-Coach, Limit-Coach, Fahrer-/Hardwareprofil, Live-Coach (lokal, ohne KI-Dienst), Sprachausgabe (Piper/SAPI)
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
0.2.3 Beta  Overlays im Stil des RaceRoom-HUDs: keine Kontur und kein Akzentbalken mehr, dezenter dunkler Verlauf, Titel in weissen Versalien, Zeilen wie im Boxenstopp-Menue (Beschriftung links grau, Wert rechts weiss). Reifen-Overlay unveraendert im Aufbau.
0.2.2 Beta  Design an das RaceRoom-Menue angeglichen: Tab-Navigation oben (aktiver Reiter weiss, Pfeile vor/zurueck), dunkler Verlaufshintergrund mit Rotstich, flache eckige Buttons, Dashboard-Kacheln und grosse Wettbewerbe-Kachel im Menue-Stil. Einstellungsfenster folgt jetzt dem gewaehlten Design.
0.2.1 Beta  Optionale KI-Anbieter fuer den Live-Coach: ChatGPT (OpenAI), Mistral, Gemini, Claude, DeepSeek. Auswahl, API-Key (unter Windows mit dem Benutzerkonto verschluesselt), Modell und Verbindungstest unter Einstellungen bzw. Coach-Menue. Die KI formuliert den Hinweis nach der Runde zu einem Funkspruch um; ohne Key, ohne Netz oder bei Fehlern bleibt der lokale Satz. Gesendet werden nur Rundennummer, Delta und Hinweistext.
0.2.0 Beta  Neues Design im RaceRoom-Stil (Seitenleiste, Kopfleiste, einheitliche Overlay-Rahmen). Deutlich geringere CPU-Last: Aufnahme und Oberflaeche entkoppelt, Overlay-Timer nur bei sichtbarem Fenster, Live-Delta gecacht. Rundenzeiten-/Pedal-/Abstand-Overlay ueberarbeitet. Kachel zu den RaceRoom-Competitions. Gemini entfernt (Live-Coach rein lokal).
0.1.5 Beta  Spiel-Stoerung behoben: Shared Memory wird nur noch geoeffnet (nie angelegt), Overlays nehmen dem Spiel nie den Fokus.
0.1.4 Beta  API-Pruefung gegen r3e.h 3.5 (Stand 03/2026, nach RaceRoom-Update 21.10.2026 unveraendert): Layout-/Versionswaechter mit Hinweis im Verbindungs-Feld.
0.1.3 Beta  Logo: PitBoss + RaceRoom kombiniert (Header und App-Icon).
0.1.2 Beta  Reifen-Overlay ein Viertel kleiner; Kurven-Coach erkennt auch leichtere Bremszonen (alle Kurven mit relevantem Tempoabbau).
0.1.1 Beta  Reifen-Overlay: Farben nach Temperaturfenster, Carc entfernt; Live-Coach fuer langsame Autos/kurze Strecken; RaceRoom-Logo; Menue Mehr aufgeraeumt; automatische Update-Pruefung beim Start.
0.1.0 Beta  Erste eigenstaendige RaceRoom-Version (Fork von PitBoss 0.5.9.31, LMU-Code entfernt).
