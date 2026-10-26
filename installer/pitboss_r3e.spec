# -*- mode: python ; coding: utf-8 -*-
# Baut PitBoss R3E als One-Folder-App (schnellerer Start, weniger AV-Fehlalarme).
# Aufruf (im Repo-Root):  pyinstaller installer/pitboss_r3e.spec --noconfirm
#
# 0.2.6 Verschlanke Build: PitBoss nutzt nur QtCore/QtGui/QtWidgets (+ QtSvg fuer die
# SVG-Icons). Alle anderen Qt-Module werden per excludes gar nicht erst gesammelt
# und nach der Analysis via DLL-/Ressourcen-Filter rausgeworfen. Von den Qt-Plugins
# bleibt nur die Whitelist (Plattform, Styles, Bildformate, Icon-Engines, Eingabe).
import fnmatch
import os

block_cipher = None
ROOT = os.path.abspath(os.getcwd())

# Datendateien: assets immer, piper nur wenn zur Build-Zeit vorhanden (CI laedt es)
_DATAS = [
    (os.path.join(ROOT, 'README.txt'), '.'),
    (os.path.join(ROOT, 'assets'), 'assets'),
]
_PIPER = os.path.join(ROOT, 'piper')
if os.path.isdir(_PIPER):
    _DATAS.append((_PIPER, 'piper'))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=_DATAS,
    hiddenimports=['win32com', 'win32com.client', 'pythoncom', 'pywintypes', 'raceroom_sm', 'ai_providers'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        # 0.2.6: alle nicht genutzten Qt-Bindings (App nutzt nur Core/Gui/Widgets/Svg)
        'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtConcurrent',
        'PySide6.QtDataVisualization', 'PySide6.QtDBus', 'PySide6.QtDesigner',
        'PySide6.QtHelp', 'PySide6.QtLocation', 'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets', 'PySide6.QtNetwork', 'PySide6.QtNetworkAuth',
        'PySide6.QtNfc', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtPositioning',
        'PySide6.QtPrintSupport', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects',
        'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialPort',
        'PySide6.QtSql', 'PySide6.QtStateMachine', 'PySide6.QtTest',
        'PySide6.QtTextToSpeech', 'PySide6.QtUiTools', 'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets',
        'PySide6.QtXml', 'tkinter',
    ],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)

# 0.2.6: Post-Analysis-Filter. PyInstaller sammelt ueber die PySide6-Hooks mehr Qt-DLLs
# und -Plugins ein als wir brauchen. Diese Eintraeger werden nachtraeglich entfernt.
# Wichtig: Qt6Svg.dll bleibt drin (SVG-Assets/Icons brauchen die + iconengines-Plugin).
_DROP_PATTERNS = [
    '*/qt63d*', '*/qt6bluetooth*', '*/qt6charts*', '*/qt6concurrent*',
    '*/qt6datavisualization*', '*/qt6dbus*', '*/qt6designer*', '*/qt6help*',
    '*/qt6location*', '*/qt6multimedia*', '*/qt6network*', '*/qt6networkauth*',
    '*/qt6nfc*', '*/qt6pdf*', '*/qt6positioning*', '*/qt6printsupport*',
    '*/qt6qml*', '*/qt6quick*', '*/qt6remoteobjects*', '*/qt6scxml*',
    '*/qt6sensors*', '*/qt6serialport*', '*/qt6shadertools*', '*/qt6spatialaudio*',
    '*/qt6sql*', '*/qt6statemachine*', '*/qt6test*', '*/qt6texttospeech*',
    '*/qt6uitools*', '*/qt6webchannel*', '*/qt6webengine*', '*/qt6websockets*',
    '*/qt6xml*', '*/translations/*',
]
_KEEP_PLUGIN_DIRS = ('platforms', 'styles', 'imageformats', 'iconengines', 'platforminputcontexts')


def _entry_name(entry):
    # TOC-Eintraege sind (dest, src, kind) - wir filtern nach dem Zielpfad.
    return (entry[0] if isinstance(entry, (list, tuple)) and len(entry) > 0 else str(entry)).replace('\\', '/')


def _drop(name):
    n = str(name).replace('\\', '/').lower()
    for pat in _DROP_PATTERNS:
        if fnmatch.fnmatch(n, pat):
            return True
    if '/plugins/' in n:
        return not any(('/plugins/' + sub + '/') in n for sub in _KEEP_PLUGIN_DIRS)
    return False


a.binaries = [e for e in a.binaries if not _drop(_entry_name(e))]
a.datas = [e for e in a.datas if not _drop(_entry_name(e))]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='PitBossR3E',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,   # GUI-App; auf True stellen, um Startfehler im Terminal zu sehen
    icon=os.path.join(ROOT, 'assets', 'pitboss_app_icon.ico'),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='PitBossR3E',
)
