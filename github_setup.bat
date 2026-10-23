@echo off
setlocal
cd /d "%~dp0"
echo == PitBoss R3E - GitHub Setup ==
where git >nul 2>nul
if errorlevel 1 goto NOGIT
where gh >nul 2>nul
if errorlevel 1 goto NOGH
gh auth status >nul 2>nul
if errorlevel 1 gh auth login
if errorlevel 1 goto NOAUTH
if not exist ".git" git init
REM Git-Identitaet lokal setzen, falls nicht vorhanden (behebt "Author identity unknown")
git config user.name  >nul 2>nul || git config user.name  "Pfoetiman76"
git config user.email >nul 2>nul || git config user.email "Pfoetiman76@users.noreply.github.com"
git branch -M main
git add -A
git commit -m "PitBoss R3E 0.1.4"
REM Sicherstellen, dass ein Commit existiert
git rev-parse HEAD >nul 2>nul
if errorlevel 1 goto NOCOMMIT
REM Repo anlegen falls noch nicht vorhanden, sonst nur Remote sicherstellen
gh repo view Pfoetiman76/pitboss-r3e >nul 2>nul
if errorlevel 1 gh repo create pitboss-r3e --public --disable-wiki
git remote get-url origin >nul 2>nul || git remote add origin https://github.com/Pfoetiman76/pitboss-r3e.git
git push -u origin main
if errorlevel 1 goto PUSHFAIL
git tag v0.1.4 2>nul
git push origin v0.1.4
echo.
echo Fertig. Installer-Build laeuft hier:
echo    https://github.com/Pfoetiman76/pitboss-r3e/actions
echo Release erscheint danach hier:
echo    https://github.com/Pfoetiman76/pitboss-r3e/releases
goto END
:NOGIT
echo [FEHLER] git fehlt. Installieren: https://git-scm.com/download/win
goto END
:NOGH
echo [FEHLER] GitHub CLI fehlt. Installieren: https://cli.github.com/
goto END
:NOAUTH
echo [FEHLER] GitHub-Login abgebrochen.
goto END
:NOCOMMIT
echo [FEHLER] Commit fehlgeschlagen - git-Identitaet pruefen.
goto END
:PUSHFAIL
echo [FEHLER] Push fehlgeschlagen. Meldung oben pruefen (evtl. Repo nicht leer oder Rechte).
:END
pause
