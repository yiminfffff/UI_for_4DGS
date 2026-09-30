@echo off
setlocal
set "TASK_ROOT=%~dp0"
set "TASK_ENV=%TASK_ROOT%.envs\hust4dgs"
for /f "usebackq tokens=*" %%I in (`"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "TASK_VS=%%I"
if not defined TASK_VS exit /b 2
call "%TASK_VS%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 3
set "PATH=%TASK_ENV%;%TASK_ENV%\Scripts;%TASK_ENV%\Library\bin;%PATH%"
set "CUDA_HOME=%TASK_ENV%\Library"
set "CUDA_PATH=%CUDA_HOME%"
set "LIB=%TASK_ENV%\Library\lib;%LIB%"
set "DISTUTILS_USE_SDK=1"
set "TORCH_CUDA_ARCH_LIST=8.9"
set "MAX_JOBS=4"
set "PYTHONUTF8=1"
set "PIP_CACHE_DIR=%TASK_ROOT%.cache\pip"
cd /d "%TASK_ROOT%HUST-Windows"
"%TASK_ENV%\python.exe" -m pip install --no-build-isolation --no-deps ./submodules/depth-diff-gaussian-rasterization ./submodules/simple-knn
exit /b %errorlevel%
