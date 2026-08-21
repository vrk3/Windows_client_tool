@echo off
setlocal

rem Runs the app from source, elevated.
rem
rem Smart App Control is enforced on this machine (CodeIntegrity event 3077),
rem so the unsigned PyInstaller build in dist\ cannot be launched at all.
rem python.exe IS signed and reputable, so SAC allows it -- running from source
rem is the way to use the app while SAC stays on.
rem
rem Double-clicking used to run UNELEVATED despite the file's name, which
rem silently dropped every admin-only module from the sidebar. It now re-launches
rem itself through UAC instead.

net session >nul 2>&1
if not errorlevel 1 goto :run

echo Requesting administrator privileges...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:run
cd /d "%~dp0src"
"%~dp0.venv\Scripts\python.exe" main.py 2> "%TEMP%\wtweaker_error.txt"
if errorlevel 1 (
    echo ERROR - see %TEMP%\wtweaker_error.txt
    type "%TEMP%\wtweaker_error.txt"
    pause
)
