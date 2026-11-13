# PitBoss R3E – Benutzerhandbuch

Telemetrie- und Coaching-App für RaceRoom Racing Experience (Windows, mit VR-Unterstützung).

<!-- AUTO:VERSION:start -->
Dieses Handbuch beschreibt **PitBoss R3E 0.4.3.1 Beta** (Stand: 2026-11-12, siehe [Releases](https://github.com/Pfoetiman76/pitboss-r3e/releases)).
<!-- AUTO:VERSION:end -->

> Hinweis: Die Zeile oben zwischen den `AUTO:VERSION`-Marken wird vom Workflow „Handbuch aktuell halten" automatisch bei jeder Änderung auf dem Hauptzweig nachgezogen – das Handbuch veraltet also nie in der Versionsangabe. Inhaltliche Ergänzungen erfolgen mit den Programm-Versionen.

## 1. Installation und Update

### Installer wählen (wichtig!)

Auf der [Releases-Seite](https://github.com/Pfoetiman76/pitboss-r3e/releases) stehen je zwei Setup-Dateien:

| Datei | Bedeutung |
| --- | --- |
| `PitBossR3E-Setup-<Version>.exe` | **Empfohlen.** Enthält die natürliche Piper-Sprachstimme (offline). |
| `PitBossR3E-Setup-Lite-<Version>.exe` | Kleinere Variante ohne Piper – Sprachausgabe fällt auf die Windows-Roboterstimme (SAPI) zurück. |

### Update

- **In der App:** Menü „Update" → „Nach Update suchen". Findet die App eine neuere Version, kann der Installer direkt heruntergeladen und gestartet werden. Die Prüfung unternimmt mehrere Versuche, falls GitHub kurzzeitig nicht antwortet.
- **Im Browser:** Releases-Seite öffnen, Setup-Datei (ohne „Lite") herunterladen und einfach über die alte Installation laufen lassen. Einstellungen und Daten bleiben erhalten.

Die Kopfleiste der App zeigt neben der Version ein farbiges Abzeichen: **VOLL** (türkis, Piper-Stimme enthalten) oder **LITE** (bernstein, ohne Piper). So siehst du jederzeit, welche Installationsvariante läuft.

## 2. Erste Schritte

1. PitBoss starten, dann RaceRoom (oder umgekehrt – die Reihenfolge ist egal).
2. Eine lesbare Session öffnen (Practice/Rennen). Telemetrie kommt nur, wenn RaceRoom sie freigibt; im Hauptmenü gibt es keine Daten.
3. Verbindung prüfen: Die Kachel „Verbindung" meldet den Zustand; Details stehen im Live-Log.

Daten (Einstellungen, Logs, Reports) liegen unter `Dokumente\PitBoss R3E`.

> Ab Version 0.4.3.0 ist der frühere Reiter „Live“ (Streckenkarte, Live-Zeile, Rundenliste mit den Unterreitern Reifen, Analyse, Runden, Vergleich, Heatmap, Sitzungen und Telemetrie) entfernt. Die Auswertung laufender Sitzungen wird in **R3E-Resultate** (Reiter „Live“) weitergeführt. Aufnahme (Recorder), Overlays, VR-Spiegel und Coaches bleiben unverändert in PitBoss.

## 3. Overlays am Monitor

- **Öffnen:** Menü „Overlays" – das Menü bleibt bei Häkchen offen (abreißbar als eigenes Fenster). Alternativ „Alle im Fenster verwalten …".
- **Verschieben:** Fenster mit der Maus ziehen.
- **Größe:** Mausrad über dem Overlay (Skalierung 30–300 %).
- **Hintergrund-Deckkraft:** Alt + Mausrad in 5-%-Schritten – die Schrift bleibt immer voll lesbar.
- **Reifen-Overlay** öffnet sich standardmäßig nicht mehr automatisch; falls gewünscht: Overlays → „Reifen-Overlay automatisch öffnen (bei Fahrt)" aktivieren.
- **Anzeige-Modus je Overlay** (Kontextmenü des Overlays oder Verwaltungsfenster): „Beide", „nur Monitor" oder „nur VR". Nur-VR-Tafeln bleiben am Monitor unsichtbar, werden aber weiter aktualisiert und in der Brille gespiegelt.

## 4. VR-Einrichtung (Virtual Desktop / VDXR)

### Einmalige Einrichtung

1. RaceRoom startet natives OpenXR **nur mit der richtigen Startoption**: Steam → Rechtsklick auf RaceRoom → Eigenschaften → Startoptionen → „RaceRoom Racing Experience (64-bit OpenXR)" wählen (oder Startparameter `-vr openxr`). Die normale „… VR"-Variante läuft über SteamVR – dort lädt die Erweiterung nie.
2. Aus dem Pre-Release [VR-Layer PoC](https://github.com/Pfoetiman76/pitboss-r3e/releases/tag/poc-vr-layer) die Dateien `XR_APILAYER_PitBossR3E_VR.dll` und `pitboss_vr_layer.json` in einen eigenen Ordner laden, z. B. `S:\PitBossVR`.
3. **Entblocken:** Rechtsklick auf jede der beiden Dateien → Eigenschaften → Häkchen „Zulassen" → OK. Windows sperrt frisch heruntergeladene Dateien; ohne diesen Schritt lädt das Spiel die Erweiterung still nicht.
4. Aktivierung per Registry (siehe `LIESMICH.txt` im Pre-Release) oder als Befehl (Pfad ggf. anpassen):
   `reg add "HKCU\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit" /v "S:\PitBossVR\pitboss_vr_layer.json" /t REG_DWORD /d 0 /f`
5. RaceRoom neu starten.

### Tafeln in der Brille bedienen

Menü „Overlays" → „VR-Overlay (Monitor 1:1)" aktivieren. Feineinstellung unter „VR: Einstellungen …": Breite, Höhe, Abstand, Deckkraft, Hintergrund, Zoom (VR-Lesbarkeit) und Overlay-Deckkraft – live wirksam.

**Anordnen-Modus** (Taste F4, frei belegbar, Stream-Deck-tauglich): das ausgewählte Overlay erhält einen Türkis-Rahmen und einen Bedienhinweis auf der Tafel. Alle Justage-Tasten wirken nur mit gehaltenem Strg+Alt, damit die Rennkamera unberührt bleibt:

| Taste (mit Strg+Alt) | Wirkung |
| --- | --- |
| Pfeiltasten | verschieben (zusätzlich Shift = 8-px-Feinschritt) |
| Plus / Minus | Größe |
| Ü / Ä | Abstand (näher / weiter weg) |
| Ö / Raute (#) | vertikal kippen |
| Komma / Punkt | horizontal kippen |
| Leertaste | nächstes Overlay |
| 1 … 9 | Overlay direkt auswählen |
| F4 (ohne Strg+Alt) | Anordnen-Modus beenden |

### Testtafel

Läuft PitBoss **nicht**, bleibt die VR-Tafel unsichtbar. Für Diagnosen kann die grüne Testtafel (Verlauf mit wanderndem Balken) aktiviert werden: im DLL-Ordner eine leere Datei `pitboss_vr_testmuster.flag` anlegen; löschen schaltet sie wieder aus. Das Layer-Protokoll meldet den Zustand beim Spielstart in `%TEMP%\PitBossVR_layer.log`.

## 5. Coaches und Sprachausgabe

- Der Live-Coach analysiert die Telemetrie und gibt Hinweise als Text und/oder Sprache (lokal, ohne Cloud; optional anbindbar).
- **Coach-Priorität (ab 0.4.3.2):** Der Kurven-Coach (Bremspunkt-Ansagen) ist zeitkritisch und hat Vorrang. Läuft gerade eine seiner Ansagen, hält der Live-Coach seinen Hinweis zurück und spricht ihn erst, wenn die Sprachausgabe frei ist – der Satz geht nicht mehr verloren und überlagert keine Bremsansage mehr.
- **Lautstärke:** Coach-Menü → „Sprachausgabe-Lautstärke …". Der Regler ist ein **Ziel-Pegel (20–100 %)**: Jede Ansage wird auf diesen Pegel angehoben (Spitzen-Normalisierung) – bei 100 % ist jede Ansage voll ausgesteuert, ohne Übersteuern. „Testansage" prüft sofort; die Einstellung wird automatisch gespeichert.
- **Backend:** Der Dialog zeigt das aktive Backend. Der Voll-Installer liefert „piper" (natürliche Stimme, offline); ohne Piper greift die Windows-Systemstimme, dort wirkt der Ziel-Pegel als Stimmlautstärke.

## 6. Problembehandlung

| Symptom | Lösung |
| --- | --- |
| Keine Telemetrie / Overlays ohne Werte | Lesbare Session fahren (Practice/Rennen, nicht Hauptmenü). Kein Effekt: Live-Log auf Reader-Fehler prüfen und melden. |
| Update-Prüfung schlägt fehl | Meist kurzzeitige GitHub-Störung; die App wiederholt automatisch. Dauerhaft: Installer über die Releases-Seite im Browser laden. |
| Ansagen sehr leise | Ziel-Pegel auf 100 % stellen; prüfen, dass der Voll-Installer installiert ist (Backend „piper"). Zusätzlich Windows-Lautstärkemixer kontrollieren (Eintrag „PitBossR3E"). |
| VR-Tafel bleibt leer | 1) R3E-OpenXR-Startoption gesetzt? 2) DLL entblockt? 3) `%TEMP%\PitBossVR_layer.log` prüfen – keine Datei heißt: Layer wird gar nicht geladen (Registry/Startoption). |
| In VR nur grüner Balken (Testmuster) | PitBoss läuft nicht oder VR-Overlay aus; oder die alte DLL ist noch im Einsatz (Testmuster früherer Versionen). DLL aus dem aktuellen Pre-Release ersetzen und entblocken. |
| Kamera bewegt sich beim Justieren | Justage-Tasten wirken nur mit gehaltenem Strg+Alt (Abschnitt 4). |

## 7. Diagnose-Dateien

- `%TEMP%\PitBossVR_layer.log` – VR-Erweiterung (Laden, Verhandlung, Overlay-Init, Testmuster-Zustand)
- `Dokumente\PitBoss R3E\logs\` – App-Protokolle
- `Dokumente\PitBoss R3E\vr_debug_canvas.png` – Leinwand-Foto bei aktivierter VR-Diagnose (zeigt, was PitBoss in die Brille schickt)

Bei Problemen genügt oft eine dieser Dateien zusammen mit einer kurzen Beschreibung – am einfachsten über die App melden (Feedback-Funktion) oder direkt im Projekt melden.

## 8. Entwicklung

Technik, Tests und Release-Ablauf: `README.md`, `README.txt` und `RELEASING.md`. Das Handbuch selbst liegt als `BENUTZERHANDBUCH.md` im Repo; die Versionszeile wird vom Workflow „Handbuch aktuell halten" automatisch synchronisiert.
