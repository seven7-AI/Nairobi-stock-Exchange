param(
    [string]$RepoPath = "D:\2026 Projects\Nairobi-stock-Exchange"
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $RepoPath "logs"
$logFile = Join-Path $logDir "monthly_task_scheduler.log"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory | Out-Null
}

Push-Location $RepoPath
try {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Starting monthly pipeline"
    
    # Use Start-Process with separate stdout and stderr files
    $stdoutFile = "$logFile.stdout.tmp"
    $stderrFile = "$logFile.stderr.tmp"
    
    $process = Start-Process -FilePath "uv" -ArgumentList "run", "nse-analysis", "generate-monthly-report" `
        -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile
    
    # Append both outputs to log file
    if (Test-Path $stdoutFile) {
        Get-Content $stdoutFile | Add-Content -Path $logFile
        Remove-Item $stdoutFile
    }
    if (Test-Path $stderrFile) {
        Get-Content $stderrFile | Add-Content -Path $logFile
        Remove-Item $stderrFile
    }
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Monthly pipeline finished"
    
    # Check exit code
    if ($process.ExitCode -ne 0) {
        Add-Content -Path $logFile -Value "[$timestamp] ERROR: Pipeline failed with exit code $($process.ExitCode)"
        exit $process.ExitCode
    }
    
    # Commit and push if git is available
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $logFile -Value "[$timestamp] Committing monthly report"
        git add reports/monthly/*.md 2>&1 | Out-Null
        $null = git diff --cached --quiet reports/monthly/*.md 2>&1
        $hasChanges = $LASTEXITCODE -ne 0
        if ($hasChanges) {
            # There are staged changes, commit and push
            git config user.name "NSE-Report-Bot" 2>&1 | Out-Null
            git config user.email "nse-report-bot@localhost" 2>&1 | Out-Null
            git commit -m "chore: add monthly NSE report" 2>&1 | Add-Content -Path $logFile
            git push 2>&1 | Add-Content -Path $logFile
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Add-Content -Path $logFile -Value "[$timestamp] Monthly report committed and pushed"
        } else {
            Add-Content -Path $logFile -Value "[$timestamp] No changes to commit"
        }
    }
}
catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] ERROR: $($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
