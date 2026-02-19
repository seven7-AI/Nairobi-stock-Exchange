param(
    [string]$TaskName = "NSE-Monthly-Report",
    [string]$Time = "19:00",  # 7 PM
    [string]$RepoPath = "D:\2026 Projects\Nairobi-stock-Exchange"
)

$ErrorActionPreference = "Stop"

$runnerScript = Join-Path $RepoPath "scripts\run_monthly_task.ps1"
if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found at $runnerScript"
}

$runnerCmd = Join-Path $RepoPath "scripts\run_monthly_task.cmd"
if (-not (Test-Path $runnerCmd)) {
    throw "CMD runner script not found at $runnerCmd"
}

# Create or overwrite task with schtasks - Monthly on last day (28th-31st)
# Note: Windows Task Scheduler doesn't support "last day of month" directly,
# so we'll schedule it for the 28th and the script will check if it's the last day
$createArgs = @(
    "/Create",
    "/SC", "MONTHLY",
    "/D", "28",  # Run on 28th, script will check if it's the last day
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

Write-Host "Monthly scheduled task created/updated."
Write-Host "Task Name: $TaskName"
Write-Host "Schedule: Monthly on 28th at $Time (script checks if last day of month)"
Write-Host "Command: $taskCommand"
Write-Host ""
Write-Host "Note: For true last-day-of-month scheduling, consider using GitHub Actions or"
Write-Host "manually updating the task to run on 28th-31st each month."

# Show final task details
schtasks /Query /TN $TaskName /V /FO LIST
