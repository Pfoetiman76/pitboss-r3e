# -*- mode: python ; coding: utf-8 -*-
# Baut PitBoss R3E als One-Folder-App (schnellerer Start, weniger AV-Fehlalarme).
# Aufruf (im Repo-Root):  pyinstaller installer/pitboss_r3e.spec --noconfirm
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
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)
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
