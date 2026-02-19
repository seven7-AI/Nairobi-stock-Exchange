param(
    [string]$RepoPath = "D:\2026 Projects\Nairobi-stock-Exchange"
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $RepoPath "logs"
$logFile = Join-Path $logDir "task_scheduler.log"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory | Out-Null
}

Push-Location $RepoPath
try {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Starting daily pipeline"
    uv run nse-analysis run-daily *>> $logFile
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Daily pipeline finished"
}
finally {
    Pop-Location
}
