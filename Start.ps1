param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$python = Join-Path $appRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $developmentPython = Join-Path (Split-Path $appRoot -Parent) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $developmentPython) { $python = $developmentPython }
    else { & (Join-Path $appRoot 'Setup.ps1') }
}
& $python -c 'import flask, PIL, mutagen, torch, numpy, scipy, soundfile, rosu_pp_py, yt_dlp, yt_dlp_ejs'
if ($LASTEXITCODE -ne 0) { throw 'Dependencies missing. Run Setup.ps1 first.' }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$launcherArgs = @('-u', (Join-Path $appRoot 'launcher.py'))
if ($NoBrowser) { $launcherArgs += '--no-browser' }
& $python @launcherArgs
exit $LASTEXITCODE
