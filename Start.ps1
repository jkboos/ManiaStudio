param([switch]$NoBrowser, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $appRoot 'python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $appRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $developmentPython = Join-Path (Split-Path $appRoot -Parent) '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $developmentPython) { $python = $developmentPython }
        else { & (Join-Path $appRoot 'Setup.ps1') }
    }
}
Push-Location -LiteralPath $appRoot
try {
    & $python -m studio.dependencies check --quiet
    if ($LASTEXITCODE -ne 0) {
        & (Join-Path $appRoot 'Setup.ps1') -PythonPath $python
        & $python -m studio.dependencies check
        if ($LASTEXITCODE -ne 0) { throw 'Dependency setup did not complete. Open Start.cmd again to retry.' }
    }
    $launcherArgs = @('-u', (Join-Path $appRoot 'launcher.py'), '--port', $Port)
    if ($NoBrowser) { $launcherArgs += '--no-browser' }
    & $python @launcherArgs
    $launcherExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $launcherExitCode
