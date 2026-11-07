# PitBoss R3E VR Layer (0.4.0.0 PoC)

Nativer OpenXR-API-Layer, der eine virtuelle Tafel in die VR-Szene von
RaceRoom einblendet. Laeuft im Spielprozess und funktioniert damit mit jeder
OpenXR-Runtime - ausdruecklich auch **Virtual Desktop / VDXR ohne SteamVR**.

## Architektur

```
PitBoss (Python)                       RaceRoom-Prozess
+---------------------+                +------------------------------+
| Overlay-Rendering   |   Shared Mem   | XR_APILAYER_PitBossR3E_VR.dll|
| -> BGRA-Bild        | =============> | liest Puffer, legt Quad-Layer|
| -> Local\PitBossR3E_VR|  (30 Hz)     | ueber die Szene (xrEndFrame) |
+---------------------+                +------------------------------+
```

Shared-Memory-Protokoll (Version 1), Name `Local\PitBossR3E_VR`:

| Offset | Typ      | Bedeutung                              |
|--------|----------|----------------------------------------|
| 0      | uint32   | Magic `0x52564250` ("PBVR")            |
| 4      | uint32   | Protokollversion (1)                   |
| 8      | uint32   | Breite (512)                           |
| 12     | uint32   | Hoehe (256)                            |
| 16     | uint32   | Bildzaehler (pro Frame +1)             |
| 20     | BGRA[512x256] | Pixel, Zeilen von oben          |

Laeuft PitBoss nicht, zeigt der Layer ein Testmuster mit wanderndem Balken
("Testtafel"). Damit ist der PoC ohne PitBoss in jeder Practice-Session
pruefbar.

## Bauen

CMake laedt die vier OpenXR-Public-Header (Khronos OpenXR-SDK 1.1.45,
Apache-2.0/MIT) beim Konfigurieren einmalig von GitHub in den Build-Ordner.
Kein SDK-Klon, keine Submodule, keine Header-Generierung noetig.

```
cmake -S vr_layer -B vr_layer/build -A x64
cmake --build vr_layer/build --config Release
```

Ergebnis: `XR_APILAYER_PitBossR3E_VR.dll` + `pitboss_vr_layer.json`.
(Die GitHub-Actions CI baut beides automatisch, siehe
`.github/workflows/vr-layer-ci.yml`; das Release-Workflow stellt beides
als oeffentliches Pre-Release "poc-vr-layer" bereit.)

## Aktivieren (impliziter Layer, Registry)

Explizite Layer werden nur geladen, wenn die Anwendung sie selbst per
`enabledApiLayers` anfordert - RaceRoom tut das nicht, Umgebungsvariablen
aktivieren deshalb KEINE Layer. Der Layer wird daher als impliziter Layer
registriert (gleiches Verfahren wie OpenKneeboard / OpenXR-Toolkit). Ein
Zielprozess-Filter im Layer sorgt dafuer, dass er nur im RaceRoom-Prozess
(RRRE.exe) aktiv wird und sich in allen anderen OpenXR-Anwendungen
vollstaendig passiv verhaelt.

Eingabeaufforderung, eine Zeile (Pfad bei anderem Ordner anpassen):

```
reg add "HKCU\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit" /v "C:\PitBossVR\pitboss_vr_layer.json" /t REG_DWORD /d 0 /f
```

Danach RaceRoom neu starten (VR-Variante). Die Tafel ist bereits im
VR-Hauptmenue sichtbar. Steam und Virtual Desktop muessen nicht neu
gestartet werden.

Deaktivieren (eine Zeile):

```
reg delete "HKCU\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit" /v "C:\PitBossVR\pitboss_vr_layer.json" /f
```

Alternativ laesst sich der Layer ueber den Wert abschalten, ohne die
Registrierung zu entfernen: `/d 1` statt `/d 0` im reg-add-Befehl.

## PoC-Einschraenkungen (bewusst, Ausbau in Folgeversionen)

- Feste Pose der Tafel im LOCAL-Raum (ueber dem Startpunkt, leicht vorn).
- Textur-Updates ueber den Immediate Context des Spiels (D3D11); Ausbau auf
  einen separaten Renderpfad folgt mit der Toter-Winkel-Anzeige.
- Eine Session; wird das Spiel ohne VR gestartet, bleibt der Layer still.
- Monitorfahrer sind unbeeinflusst - der Layer wirkt nur im VR-Prozess.
- Verhandlung: Loader-Interface v1 (xrCreateApiLayerInstance mit nextInfo-
  Kette, siehe openxr_loader_negotiation.h).

## Verwandte Dateien

- `blindspot.py` / `test_blindspot.py` - Toter-Winkel-Erkennung (Python)
  inklusive Selftests (`python test_blindspot.py`, 25/25 bestanden).
