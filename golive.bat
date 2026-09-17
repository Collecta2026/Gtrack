@echo off
REM ---------------------------------------------------------------------------
REM  golive - put this Python web app online (Neon + GitHub + Render)
REM  Copy this file and golive.py into a project folder, then double-click this.
REM  See README.md for where to get the three API tokens.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo.
echo   golive
echo   ======
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo   Python was not found on this machine.
    echo.
    echo   Install it from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup.
    echo   Then close this window and run golive.bat again.
    echo.
    pause
    exit /b 1
)

where git >nul 2>&1
if errorlevel 1 (
    echo   git was not found on this machine.
    echo.
    echo   Install it from https://git-scm.com/downloads, then close this
    echo   window and run golive.bat again.
    echo.
    pause
    exit /b 1
)

if not exist "golive.py" (
    echo   golive.py is not in this folder.
    echo   Copy it in alongside this file, then try again.
    echo.
    pause
    exit /b 1
)

%PY% golive.py %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   Finished successfully.
) else (
    echo   Stopped with code %RC%. Read the message above - nothing already
    echo   completed has been undone, and running this again resumes from
    echo   where it stopped.
)
echo.
pause
exit /b %RC%
