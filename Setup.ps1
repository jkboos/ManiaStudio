param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = $PythonPath
if (-not $python) {
    $python = Join-Path $PSScriptRoot 'python\python.exe'
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git')) {
        foreach ($candidate in @(
            (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
            (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe')
        )) {
            if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
        }
    }
    if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
}
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Creating a Python 3.11 environment for the source checkout...'
    py -3.11 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'For the source checkout, install Python 3.11; the portable bundle already includes Python.' }
}
& $python -m studio.dependencies install
if ($LASTEXITCODE -ne 0) { throw 'Setup did not finish. Check your connection and free disk space, then open Start.cmd again.' }
