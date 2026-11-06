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
`.github/workflows/vr-layer-ci.yml`.)

## Aktivieren (expliziter Layer, ohne Registry-Eingriff)

Eingabeaufforderung, dann RaceRoom aus **demselben** Fenster starten:

```
set XR_APILAYER_PATH=C:\Pfad\zum\Layer   (Ordner mit der JSON)
set XR_API_LAYER_PATH=X:XR_APILAYER_PitBossR3E_VR
RaceRoom.exe
```

Deaktivieren: Umgebungsvariablen nicht setzen. Nichts wird dauerhaft im
System registriert.

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
