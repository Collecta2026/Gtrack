@echo off
REM ===================================================================
REM  Gtrack - Import & Equipment Tracking
REM  Double-click this file to install, build the test database and run.
REM ===================================================================
setlocal

REM Gtrack uses its own GTRACK_DATABASE_URL. Clear any stray value for this
REM window so a test run can never touch another application's database.
set GTRACK_DATABASE_URL=

REM Prefer the Windows Python launcher, fall back to python on PATH.
where py >nul 2>&1
if %errorlevel%==0 (set PY=py) else (set PY=python)

echo.
echo  [1/3] Installing dependencies...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo  [2/3] Building the test database...
if exist "instance\gtrack.db" (
    echo        An existing database was found - keeping it.
    echo        Delete instance\gtrack.db first if you want a clean rebuild.
    %PY% seed.py --keep
) else (
    %PY% seed.py
)
if errorlevel 1 goto :failed

echo.
echo  [3/3] Starting Gtrack...
echo        Open http://127.0.0.1:5000 in your browser.
echo        Sign in with any demo account, password: demo1234
echo        Close this window or press Ctrl+C to stop.
echo.
%PY% run.py
if errorlevel 1 goto :failed
goto :end

:failed
echo.
echo  ---------------------------------------------------------------
echo   Something went wrong. The message above says what.
echo   Common fixes:
echo     - Python not found: install it from python.org, tick
echo       "Add Python to PATH" during setup, then try again.
echo     - Permission errors on install: try
echo       %PY% -m pip install --user -r requirements.txt
echo     - A package fails to COMPILE: your Python may be too new for it.
echo       Gtrack needs no compiler, so check you are not installing
echo       requirements-deploy.txt (that one is for servers only).
echo  ---------------------------------------------------------------
echo.

:end
pause
endlocal
