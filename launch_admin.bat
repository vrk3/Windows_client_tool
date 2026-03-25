@echo off
cd /d "%~dp0src"
"%~dp0.venv\Scripts\python.exe" main.py 2> "%TEMP%\wtweaker_error.txt"
if errorlevel 1 (
    echo ERROR - see %TEMP%\wtweaker_error.txt
    type "%TEMP%\wtweaker_error.txt"
    pause
)
