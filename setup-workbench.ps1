$ErrorActionPreference = 'Stop'
$workbenchRoot = $PSScriptRoot
$workbenchBase = Join-Path $workbenchRoot '.envs\hust4dgs\python.exe'
$workbenchEnv = Join-Path $workbenchRoot '.envs\workbench'
if (-not (Test-Path (Join-Path $workbenchEnv 'Scripts\python.exe'))) {
    & $workbenchBase -m venv $workbenchEnv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the desktop environment.' }
}
& (Join-Path $workbenchEnv 'Scripts\python.exe') -m pip install --disable-pip-version-check --cache-dir (Join-Path $workbenchRoot '.cache\pip') -r (Join-Path $workbenchRoot 'workbench\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the desktop dependencies.' }
Write-Host 'Ready. Double-click start-workbench.cmd.'
