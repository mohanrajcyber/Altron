@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0..\..\..\.venv\Scripts\python.exe"
if exist "%PYTHON%" (
    "%PYTHON%" -c "import sys" >nul 2>&1
    if not errorlevel 1 goto run_altron
    echo Skipping unusable Python environment: %PYTHON%
)

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON%" (
    "%PYTHON%" -c "import sys" >nul 2>&1
    if not errorlevel 1 goto run_altron
    echo Skipping unusable Python environment: %PYTHON%
)

where python >nul 2>&1
if errorlevel 1 (
    echo No working Python interpreter found for ALTRON.
    pause
    exit /b 1
)
set "PYTHON=python"
python -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Python from PATH is not usable. Repair the workspace environment and retry.
    pause
    exit /b 1
)

:run_altron
echo Starting ALTRON with %PYTHON%...
"%PYTHON%" -m altron app
set "ALTRON_EXIT=%ERRORLEVEL%"

if not "%ALTRON_EXIT%"=="0" (
    echo.
    echo ALTRON exited with error code %ALTRON_EXIT%.
    pause
)

exit /b %ALTRON_EXIT%