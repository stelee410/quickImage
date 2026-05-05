@echo off
REM quickImage CLI entry point.
REM Calls the `sd` script installed into the comfyui-rocm portable python env.
REM
REM If you move comfyui-rocm or use a different python install, edit
REM the SD_PYTHON variable below.

setlocal
set "PYTHONIOENCODING=utf-8"
if not defined SD_PYTHON set "SD_PYTHON=D:\comfyui-rocm\python_env\python.exe"

if not exist "%SD_PYTHON%" (
    echo [sd] Python interpreter not found: %SD_PYTHON%
    echo [sd] Set SD_PYTHON to the right path or reinstall the package.
    exit /b 2
)

"%SD_PYTHON%" -m sdcli %*
exit /b %ERRORLEVEL%
