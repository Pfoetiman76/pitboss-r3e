; Inno Setup Skript fuer PitBoss R3E
; Baut aus dist\PitBossR3E\ einen Windows-Installer.
; Version kommt aus der Umgebungsvariable APP_VERSION (in CI aus dem Git-Tag).
;
; 0.2.6: Zwei Varianten aus einem dist-Ordner:
;   iscc installer\setup.iss          -> PitBossR3E-Setup-<Version>.exe      (mit Piper-Stimme)
;   iscc /DLITE installer\setup.iss    -> PitBossR3E-Setup-Lite-<Version>.exe (ohne Piper,
;                                          Sprachausgabe faellt auf Windows-SAPI zurueck)
; 0.4.2.10-CI: Korrektur des piper-Quellpfads - PyInstaller 6 legt Datendateien
; unter dist\PitBossR3E\_internal ab, NICHT direkt neben die EXE. Der alte Pfad
; liess den Voll-Installer still scheitern (nur Lite wurde gebaut und an
; Releases angehaengt).
#define AppName "PitBoss R3E"
#ifndef AppVer
  #define AppVer GetEnv("APP_VERSION")
#endif
#if AppVer == ""
  #define AppVer "0.0.0"
#endif
#ifdef LITE
  #define AppSuffix "Lite-"
#else
  #define AppSuffix ""
#endif

[Setup]
AppName={#AppName}{#AppSuffix}
AppVersion={#AppVer}
AppPublisher=PitBoss R3E
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName} {#AppVer} {#AppSuffix}
OutputDir=Output
OutputBaseFilename=PitBossR3E-Setup-{#AppSuffix}{#AppVer}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
; Lite-Installer bekommt eigenes Icon mit LITE-Banner (assets\pitboss_app_icon_lite.ico)
#ifdef LITE
SetupIconFile=..\assets\pitboss_app_icon_lite.ico
#else
SetupIconFile=..\assets\pitboss_app_icon.ico
#endif
UninstallDisplayIcon={app}\PitBossR3E.exe

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Zusaetzliche Symbole:"

[Files]
; Haupt-App; im Lite-Build wird der piper-Ordner ausgeschlossen
Source: "..\dist\PitBossR3E\*"; DestDir: "{app}"; Excludes: "piper"; Flags: recursesubdirs createallsubdirs ignoreversion
#ifndef LITE
Source: "..\dist\PitBossR3E\_internal\piper\*"; DestDir: "{app}\piper"; Flags: recursesubdirs createallsubdirs ignoreversion
#endif

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\PitBossR3E.exe"
Name: "{group}\{#AppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\PitBossR3E.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PitBossR3E.exe"; Description: "{#AppName} starten"; Flags: nowait postinstall skipifsilent
