@echo off
cd /d "%~dp0"
set QT_LOGGING_RULES=*.warning=false
python main.py 2>nul
pause
