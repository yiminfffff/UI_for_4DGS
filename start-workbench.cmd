@echo off
setlocal
set "WB_ROOT=%~dp0"
set "WB_PYTHON=%WB_ROOT%.envs\workbench\Scripts\pythonw.exe"
if not exist "%WB_PYTHON%" (
    echo The desktop environment is missing. Run setup-workbench.ps1 first.
    pause
    exit /b 1
)
start "4DGS Workbench" "%WB_PYTHON%" "%WB_ROOT%workbench\main.py"
