param(
    [string]$TaskName = "NSE-Daily-Report",
    [string]$Time = "09:20",
    [string]$RepoPath = "D:\2026 Projects\Nairobi-stock-Exchange"
)

$ErrorActionPreference = "Stop"

$runnerScript = Join-Path $RepoPath "scripts\run_daily_task.ps1"
if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found at $runnerScript"
}

$runnerCmd = Join-Path $RepoPath "scripts\run_daily_task.cmd"
if (-not (Test-Path $runnerCmd)) {
    throw "CMD runner script not found at $runnerCmd"
}

# Create or overwrite task with schtasks using explicit argument list
$createArgs = @(
    "/Create",
    "/SC", "DAILY",
    "/ST", $Time,
    "/TN", $TaskName,
    "/TR", "`"$runnerCmd`"",
    "/F"
)
$createProcess = Start-Process -FilePath "schtasks.exe" -ArgumentList $createArgs -NoNewWindow -Wait -PassThru
if ($createProcess.ExitCode -ne 0) {
    throw "Failed to create task. Exit code: $($createProcess.ExitCode)"
}

$taskCommand = "`"$runnerCmd`""

Write-Host "Scheduled task created/updated."
Write-Host "Task Name: $TaskName"
Write-Host "Time: $Time"
Write-Host "Command: $taskCommand"

# Show final task details
schtasks /Query /TN $TaskName /V /FO LIST
