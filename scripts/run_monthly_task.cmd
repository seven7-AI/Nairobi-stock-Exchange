@echo off
setlocal

set "REPO_PATH=D:\2026 Projects\Nairobi-stock-Exchange"
set "LOG_DIR=%REPO_PATH%\logs"
set "LOG_FILE=%LOG_DIR%\monthly_task_scheduler.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] Starting monthly pipeline >> "%LOG_FILE%"
cd /d "%REPO_PATH%"
uv run nse-analysis generate-monthly-report >> "%LOG_FILE%" 2>&1
echo [%date% %time%] Monthly pipeline finished >> "%LOG_FILE%"

REM Commit and push if git is available
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] Committing monthly report >> "%LOG_FILE%"
    git add reports/monthly/*.md >> "%LOG_FILE%" 2>&1
    git diff --cached --quiet reports/monthly/*.md
    if %ERRORLEVEL% NEQ 0 (
        REM There are staged changes, commit and push
        git config user.name "NSE-Report-Bot" >> "%LOG_FILE%" 2>&1
        git config user.email "nse-report-bot@localhost" >> "%LOG_FILE%" 2>&1
        git commit -m "chore: add monthly NSE report" >> "%LOG_FILE%" 2>&1
        git push >> "%LOG_FILE%" 2>&1
        echo [%date% %time%] Monthly report committed and pushed >> "%LOG_FILE%"
    ) else (
        echo [%date% %time%] No changes to commit >> "%LOG_FILE%"
    )
)

endlocal
