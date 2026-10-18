# Release-Anleitung PitBoss R3E

Repo: `Pfoetiman76/pitboss-r3e` (in `updater.py` als `GITHUB_REPO` gesetzt).

## Erstes Release
Voraussetzung: **git** und **GitHub CLI** (`gh auth login`). Dann das jeweilige `deploy_<version>.bat` ausfuehren
(legt das Repo an, pusht, setzt Tag `vX.Y.Z`). GitHub Actions baut den Installer
`PitBossR3E-Setup-0.1.0.exe` und haengt ihn ans Release.

## Neues Release
1. `APP_VERSION` in `main.py` erhoehen.
2. Committen, Tag `vX.Y.Z` setzen (muss zur Version passen), `git push origin main --tags`.
3. Nutzer sehen das Update unter **Mehr -> Nach Updates suchen**.

## Lokal bauen
```
pip install PySide6 pywin32 pyinstaller
pyinstaller installer/pitboss_r3e.spec --noconfirm
iscc installer\setup.iss
```
