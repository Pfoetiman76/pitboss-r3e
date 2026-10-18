@echo off
setlocal
REM PitBoss R3E 0.1.2 - Deploy. Im entpackten Ordner ausfuehren (neben main.py).
cd /d "%~dp0"
set VER=0.1.2
set REPO=Pfoetiman76/pitboss-r3e
echo == PitBoss R3E %VER% - Deploy ==

REM --- Dateien pruefen
if not exist main.py goto NOFILE
if not exist raceroom_sm.py goto NOFILE
if not exist assets\r3e_names.json goto NOFILE
if not exist .github\workflows\release.yml goto NOFILE
if not exist installer\pitboss_r3e.spec goto NOFILE
findstr /C:"APP_VERSION = \"%VER% Beta\"" main.py >nul || goto BADVER
findstr /C:"Pfoetiman76/pitboss-r3e" updater.py >nul || goto BADREPO
findstr /C:"R3EReader(Sample)" main.py >nul || goto BADMAIN

where git >nul 2>nul || goto NOGIT
where gh >nul 2>nul || goto NOGH
gh auth status >nul 2>nul || gh auth login
gh auth status >nul 2>nul || goto NOAUTH

if not exist ".git" git init
git config user.name  >nul 2>nul || git config user.name  "Pfoetiman76"
git config user.email >nul 2>nul || git config user.email "Pfoetiman76@users.noreply.github.com"
git branch -M main
git add -A
git commit -m "PitBoss R3E %VER%"

gh repo view %REPO% >nul 2>nul || gh repo create %REPO% --public --disable-wiki
git remote get-url origin >nul 2>nul && git remote set-url origin https://github.com/%REPO%.git
git remote get-url origin >nul 2>nul || git remote add origin https://github.com/%REPO%.git
git push -u origin main --force
if errorlevel 1 goto PUSHFAIL

REM --- Tag neu setzen (altes Remote-Tag zuerst loeschen)
git push origin :refs/tags/v%VER% >nul 2>nul
git tag -d v%VER% >nul 2>nul
git tag v%VER%
git push origin v%VER%
if errorlevel 1 goto PUSHFAIL

echo.
echo Verifikation:
git ls-remote --tags origin v%VER%
echo Fertig. Build: https://github.com/%REPO%/actions
echo Release: https://github.com/%REPO%/releases/tag/v%VER%
goto END
:NOFILE
echo [FEHLER] Dateien fehlen - Skript muss im entpackten PitBoss-R3E-Ordner liegen (main.py, raceroom_sm.py, assets, .github, installer).
goto END
:BADVER
echo [FEHLER] main.py hat nicht APP_VERSION %VER% Beta.
goto END
:BADREPO
echo [FEHLER] updater.py zeigt nicht auf %REPO%.
goto END
:BADMAIN
echo [FEHLER] main.py nutzt nicht den RaceRoom-Reader.
goto END
:NOGIT
echo [FEHLER] git fehlt: https://git-scm.com/download/win
goto END
:NOGH
echo [FEHLER] GitHub CLI fehlt: https://cli.github.com/
goto END
:NOAUTH
echo [FEHLER] GitHub-Login fehlgeschlagen.
goto END
:PUSHFAIL
echo [FEHLER] Push fehlgeschlagen - Meldung oben pruefen.
:END
pause
