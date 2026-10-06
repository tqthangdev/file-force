@echo off
rem Launch FileForge (Windows).
rem
rem Creates the virtual environment and installs the runtime dependencies from
rem pyproject.toml if they are missing, then runs run.py.
rem
rem Usage:
rem   start.bat [args passed to run.py]

setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

REM Pick a bootstrap interpreter (py launcher if present, else python).
set "BOOTSTRAP=python"
where py >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP=py -3"

if not exist "%VENV_PY%" (
    echo Creating virtual environment in %VENV_DIR% ...
    %BOOTSTRAP% -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
)

"%VENV_PY%" -c "import PyQt6, PIL, platformdirs" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies ...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -e "."
    if errorlevel 1 goto :error
)

"%VENV_PY%" run.py %*
goto :eof

:error
echo.
echo Failed to start FileForge. See the messages above.
pause
exit /b 1
