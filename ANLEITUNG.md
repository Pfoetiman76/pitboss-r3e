# PitBoss R3E – Komplette Anleitung

Stand: Version 0.2.34 Beta

PitBoss R3E ist die Telemetrie- und Coaching-Software für RaceRoom Racing Experience. Die App liest die Fahrdaten direkt aus dem Spiel (Shared Memory, keine Einrichtung im Spiel nötig), zeichnet sie auf, wertet Runden aus und gibt Fahrhinweise.

---

## 1. Installation

1. Öffne [github.com/Pfoetiman76/pitboss-r3e/releases](https://github.com/Pfoetiman76/pitboss-r3e/releases)
2. Klicke bei der neuesten Version auf **`PitBoss-R3E-Setup-x.y.z.exe`** und lade sie herunter
3. Doppelklick auf die Datei → Installationsassistent folgt den Windows-Schritten (Weiter → Installieren → Fertig)
4. PitBoss startet über das Desktop-Symbol

**Voraussetzungen:** Windows, RaceRoom Racing Experience (Steam, läuft auf demselben PC). Kein Steam-Link/Cloud-PC – PitBoss liest die Daten lokal.

---

## 2. Erster Start und Ordnerstruktur

PitBoss startet direkt mit dem Dashboard - alle Ansichten sind über die Reiter oben erreichbar.

| Ordner | Inhalt |
|---|---|
| `reports` | Automatisch gespeicherte Auswertungen (TXT) |
| `csv` | Rohdaten jeder Aufzeichnung (CSV) |
| `references` | Exportierte Referenzrunden |
| `feedback` | Offline gespeicherte Beta-Feedback-Dateien |
| `logs` | Protokolldateien (zur Fehleranalyse) |
| `profile_assets` | Fahrerprofil-Bilder |

---

## 3. Verbindung zu RaceRoom

- PitBoss muss laufen, **bevor oder während** RaceRoom läuft – die Reihenfolge ist egal, die Verbindung kommt automatisch, sobald du in einer Session bist
- Dashboard-Kachel „Verbindung" zeigt **„RaceRoom verbunden"**, sobald Daten fließen
- Steht dort „Wartet auf RaceRoom": Spiel starten und in eine Practice-Session fahren

---

## 4. Aufzeichnen – der wichtigste Ablauf

**PitBoss zeichnet NICHT automatisch auf.** Du startest und stoppst die Aufnahme selbst:

1. Roter Button **„● AUFNAHME STARTEN"** (oben) klicken – oder Taste **F8**
   - Statusleiste zeigt „🔴 RECORDING AKTIV"
2. **Jetzt erst** in RaceRoom losfahren
3. Fahren … die Rundendaten sammeln sich automatisch (ca. 10 Werte pro Sekunde)
4. Stoppen: Button **„■ AUFNAHME STOPPEN"** oder **F8**
5. Es erscheint der **Speichern-Dialog**:
   - „Report + CSV wurden gespeichert" mit den genauen Pfaden – fertig
   - „Es wurde KEIN Report gespeichert" mit Grund und häufigen Ursachen
   - Bei Speicherfehlern: konkrete Fehlermeldung und Ziel-Ordner
   - Button **„Ordner öffnen"** springt direkt zu den Dateien

**Sicherheitsnetze:**
- Wird PitBoss mit laufender Aufnahme geschlossen, stoppt und speichert es automatisch
- Beendetest du RaceRoom während der Aufnahme: Nach ca. 5 Sekunden eingefrorener Telemetrie stoppt und speichert PitBoss automatisch
- Wechselst du Strecke oder Fahrzeug, wird die laufende Aufnahme gespeichert und eine neue gestartet („Auto-Wechsel", abschaltbar unter Mehr)

---

## 5. Runden auswerten

### Rundentabelle
Jede erkannte Runde erscheint mit Status:

- **gültig** – saubere Runde
- **ausgeschlossen** – ungültig (z. B. abgewinkelt wegen Track-Limits)
- **ungültig (einbezogen)** – ungültig, aber mit in der Auswertung (siehe Abschnitt 5.3)
- **REFERENZ** – die Rundenauswertungs-Basis

### Referenz- und Vergleichsrunde
- **Referenz** = deine beste saubere Runde (Automatik) oder manuell gewählt
- **Vergleich** = die Runde, gegen die gefahren wird (Standard: Auto)
- Beide lassen sich oben in den Auswahllisten (Combos) festlegen
- Die Sektor-Anzeige zeigt dann, wo du gegen die Referenz Zeit verlierst oder gewinnst (+/− Sekunden pro Streckenabschnitt)

### Ungültige Runden einbeziehen (seit 0.2.31)
Abgewinkelte Runden haben trotzdem brauchbare Fahrdaten. Wenn du sie mit auswerten willst:

1. Menü **Mehr** → **„Ungültige Runden in Auswertung (inkl. Referenz/Vergleich)"** aktivieren
2. Alle Auswertungen (Referenz, Vergleich, Sektor-Deltas, Auto-Bestlap-Export) rechnen sofort neu
3. Die Einstellung wird gespeichert und gilt auch beim nächsten Start

Hinweis: Eine durch Abkürzen „geschenkte" Zeit verfälscht Referenz-Vergleiche – deshalb ist der Schalter standardmäßig aus.

### Weitere Auswertungen
- **Heatmap**: Streckenverlauf, gefärbt nach Geschwindigkeit – rote Abschnitte = langsam
- **Coach-Zonen**: die wichtigsten Verbesserungspunkte als Text (Bremspunkte, Tempo, Linie)
- **Reifenanalyse**: Temperaturen, Druck, Verschleiß-Schätzung pro Runde

---

## 6. Telemetrie-Reiter (seit 0.2.21)

Der Reiter „Telemetrie" zeigt die gefahrenen Kanäle im Stil professioneller Auswertungssoftware:

- **Trace (schwarzer Plot)**: Gas (grün) und Bremse (rot) als Kurve 0–100 %, Lenkung zentriert
- **Runden-Auswahl oben rechts**: „Alle Runden" oder eine konkrete Runde anzeigen
- **Input-Karte (rechts)**: die Strecke, gefärbt nach Gas (grün) / Bremse (rot), dein Positionspunkt in Gelb
- **Cursor ziehen**: mit der Maus in den Trace klicken und ziehen – der gelbe Positionsstreifen und der Punkt auf der Karte wandern mit
- **„Live folgen"**: zurückschalten zur automatischen Verfolgung der aktuellen Position

---

## 7. Overlays (in-game-Fenster)

Menü oben **„Overlays ▾"** oder Hotkeys. Alle Overlays sind rahmenlose Fenster für den zweiten Monitor:

| Overlay | Zweck |
|---|---|
| Reifen-Overlay (F6) | Temperaturen, Druck, Verschleiß live |
| Monitor-Overlay (F10) | Kompakte Fahrdaten |
| Rundenzeiten (Delta/Prognose) | Aktuelle Runde gegen Referenz |
| Rundenzeiten-Graph | Zeitverlauf der Runden |
| Flaggen | Flaggen-Anzeige |
| Überholalarm | Autos direkt hinter dir |
| Abstand & Distanz | Abstände nach vorn/hinten |
| Boxenstopp | Status in der Boxengasse |
| Fahrzeugschäden | Schadensanzeige |
| Toter Winkel | Autos im toten Winkel (Seiten spiegelnbar) |
| Bremstemperaturen | inkl. Verschleiß-Schätzung |
| Kraftstoff | Sprit-Management |
| Pedal-Overlay | Gas/Bremse/Kupplung |

---

## 8. Hotkeys

Standardbelegung (alle unter **Mehr → „Hotkeys belegen …"** frei änderbar, F1–F24 und 0–9):

| Taste | Aktion |
|---|---|
| F6 | Reifen-Overlay ein/aus |
| F7 | Auto-Bestlap-Export ein/aus |
| F8 | Aufzeichnung starten/stoppen (inkl. Auto-Speichern) |
| F9 | Snapshot (einzelner Datenpunkt + Status) |
| F10 | Monitor-Overlay ein/aus |
| F11 | Live-Coach (Sprachansagen) ein/aus |
| F12 | Bremsen-Coach ein/aus |

Die Hotkeys funktionieren auch, wenn RaceRoom im Vordergrund ist.

---

## 9. Reports, CSV und Sitzungs-Browser

- **Report (TXT)**: landet bei jedem Aufzeichnungs-Stopp in `Dokumente\PitBoss R3E\reports` – enthält Rundenliste mit Status, Sektor-Deltas, Coach-Zonen, Reifen- und Bremsanalyse
- **CSV**: dieselben Rohdaten in `csv` – für eigene Auswertungen (jede Zeile = ein Messpunkt)
- **Sitzungs-Browser** (im Hauptfenster): listet alle gespeicherten Aufzeichnungen mit Datum, Strecke, Fahrzeug, Runden und Bestzeit
  - Doppelklick oder „Report anzeigen": Report lesen
  - Umbenennen: eigener Name für die Sitzung
  - Alte Aufzeichnungen laden und erneut in der Ansicht durchsehen

---

## 10. Beta-Feedback senden (seit 0.2.33/0.2.34)

Menü **Mehr → „Beta-Feedback senden (Bug/Wunsch) …"**

1. **Kategorie** wählen: Bug / Fehler, Änderungswunsch oder Frage / Unklarheit
2. **Kurzer Titel** (wird der E-Mail-Betreff)
3. **Beschreibung**: was ist passiert, was hast du erwartet, wie kann man es nachstellen?
4. Optional (standardmäßig an): Version, zuletzt gefahrenes Fahrzeug und Log-Auszug (letzte 30 Zeilen) werden automatisch angehängt
5. Absenden:
   - **„Per E-Mail senden" (empfohlen):** öffnet dein Mail-Programm mit fertig ausgefüllter E-Mail an den Entwickler – nur noch „Senden" klicken. Der komplette Text liegt zusätzlich in der Zwischenablage (Strg+V), falls das Mail-Programm den langen Log-Auszug kürzt
   - **„In GitHub öffnen":** vor-ausgefülltes Issue im Browser (GitHub-Account nötig)
   - **„Kopieren & als Datei speichern":** Text in Zwischenablage + Datei unter `Dokumente\PitBoss R3E\feedback`, Ordner öffnet sich – zum Weitergeben per Mail/Discord

---

## 11. Fehlerbehebung

| Problem | Lösung |
|---|---|
| Kein Report nach dem Stopp | Speichern-Dialog zeigt den Grund. Häufigster Fall: Aufnahme gestartet, aber nicht danach gefahren, oder RaceRoom lieferte keine Daten. Log in `logs` prüfen |
| „Wartet auf RaceRoom" | RaceRoom starten und in eine Session fahren; PitBoss auf demselben PC |
| „Telemetrie eingefroren" im Log | RaceRoom wurde beendet oder die Session verlassen – Aufnahme wurde automatisch gespeichert |
| Runde fehlt / „ausgeschlossen" | Runde war ungültig (abgewinkelt). Zum Einbeziehen: Mehr → „Ungültige Runden in Auswertung" |
| Overlay bleibt nach dem Beenden stehen | Aufzeichnung/Überbleibsel seit 0.2.19 behoben – bei Wiederholung: PitBoss einmalig neu starten und Log schicken |
| F8 reagiert doppelt (Start+Stop sofort) | Bekannter Windows-Schlüsselwiederholungs-Effekt; PitBoss ignoriert Doppelklicks automatisch |
| App schließen, Daten weg? | Nein – seit 0.2.29 stoppt und speichert das Schließen die Aufnahme automatisch |
| Update installieren | Setup-EXE der neuen Version einfach drüber installieren; alle Daten und Einstellungen bleiben erhalten |

Bei hartnäckigen Fehlern: `Dokumente\PitBoss R3E\logs` – die neueste Datei per Beta-Feedback-Formular mitschicken (Log-Auszug wird automatisch angehängt).

---

## 12. Versionshistorie (Kurzform)

- **0.2.21** – Telemetrie-Reiter (Spuren, G-G-Diagramm)
- **0.2.24** – Trace im professionellen Stil (schwarz, Raster)
- **0.2.25/0.2.26** – Runden-Auswahl, Input-Karte, Positionspunkt
- **0.2.27** – Cursor mit der Maus ziehbar, „Live folgen"
- **0.2.28** – Input-Karte zeigt die echte Streckenform wie die Heatmap
- **0.2.29** – Auto-Save beim Schließen der App
- **0.2.30** – Klartext-Dialog nach dem Stopp (gespeichert/Grund/Fehler)
- **0.2.31/0.2.32** – Ungültige Runden optional in der Auswertung, konsistent im Report
- **0.2.33/0.2.34** – Beta-Feedback-Formular, bevorzugt per E-Mail

Fragen, Bugs, Wünsche: **Mehr → Beta-Feedback senden** – danke für jedes Feedback!
