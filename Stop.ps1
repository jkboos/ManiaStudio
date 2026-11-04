$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'workspace\server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No recorded Studio process.'; exit 0 }
$studioPid = [int](Get-Content -LiteralPath $pidFile)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$studioPid"
$server = Join-Path $PSScriptRoot 'server.py'
if ($process -and $process.CommandLine.Contains($server)) {
    taskkill.exe /PID $studioPid /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop Studio.' }
    Write-Host 'Mania Studio stopped.'
}
Remove-Item -LiteralPath $pidFile
