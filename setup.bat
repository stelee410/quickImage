@echo off
REM quickImage setup for Windows.
REM
REM What this does (idempotent — safe to re-run):
REM   1. Locate a Python interpreter (the comfyui-rocm portable env by default).
REM   2. pip install -e . into that interpreter.
REM   3. Add bin\ to the user PATH.
REM   4. Initialise the config and point it at the comfyui-rocm install.
REM   5. Run `sd info` as a smoke test.
REM
REM Pass /python <path> to override the interpreter, or set %SD_PYTHON%.

setlocal EnableExtensions EnableDelayedExpansion

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
cd /d "%REPO_ROOT%"

REM --- argument parsing -----------------------------------------------------
set "ARG_PYTHON="
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/python" (
    set "ARG_PYTHON=%~2"
    shift
    shift
    goto parse_args
)
echo [setup] unknown argument: %~1
exit /b 2
:args_done

REM --- 1. find Python -------------------------------------------------------
set "PY="
if defined ARG_PYTHON set "PY=%ARG_PYTHON%"
if not defined PY if defined SD_PYTHON set "PY=%SD_PYTHON%"
if not defined PY if exist "D:\comfyui-rocm\python_env\python.exe" set "PY=D:\comfyui-rocm\python_env\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [fail] no Python found. Install Python ^>=3.11 or pass /python ^<path^>.
    exit /b 1
)
echo [ ok ] python: %PY%
"%PY%" -c "import sys; assert sys.version_info >= (3,11), sys.version" 2>nul
if errorlevel 1 (
    echo [fail] %PY% is older than 3.11.
    exit /b 1
)

REM --- 2. editable install --------------------------------------------------
echo [setup] installing sdcli (editable)
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -e .
if errorlevel 1 (
    echo [fail] pip install failed
    exit /b 1
)
echo [ ok ] sdcli installed

REM --- 3. add bin to PATH ---------------------------------------------------
where powershell.exe >nul 2>nul
if errorlevel 1 (
    echo [warn] PowerShell not on PATH; skipping PATH update.
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\bin\add-to-path.ps1"
)

REM --- 4. point config at the comfyui-rocm install --------------------------
echo [setup] writing initial config
call "%REPO_ROOT%\bin\sd.cmd" config path >nul
if errorlevel 1 (
    echo [warn] could not run sd.cmd — make sure %REPO_ROOT%\bin is on PATH.
) else (
    if exist "D:\comfyui-rocm\main.py" (
        call "%REPO_ROOT%\bin\sd.cmd" config set server.install_dir "D:\comfyui-rocm" >nul
        call "%REPO_ROOT%\bin\sd.cmd" config set server.python "D:\comfyui-rocm\python_env\python.exe" >nul
        call "%REPO_ROOT%\bin\sd.cmd" config set server.launcher "D:\comfyui-rocm\start-detached.ps1" >nul
        call "%REPO_ROOT%\bin\sd.cmd" config set paths.models_dir "D:\comfyui-rocm\models" >nul
        call "%REPO_ROOT%\bin\sd.cmd" config set paths.output_dir "D:\comfyui-rocm\output" >nul
    )
)

REM --- 5. aria2c hint -------------------------------------------------------
where aria2c >nul 2>nul
if errorlevel 1 (
    echo [warn] aria2c not found — model downloads will be slow.
    echo        Install with: winget install aria2.aria2
) else (
    echo [ ok ] aria2c on PATH
)

REM --- 6. smoke test --------------------------------------------------------
echo [setup] running 'sd info'
call "%REPO_ROOT%\bin\sd.cmd" info

echo.
echo [ ok ] setup complete.
echo.
echo Next steps:
echo   - Open a new terminal so PATH picks up.
echo   - sd server start
echo   - sd models pull --recommend sdxl
echo   - sd gen "a serene mountain at sunrise"

endlocal
exit /b 0
