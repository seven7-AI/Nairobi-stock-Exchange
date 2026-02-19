@echo off
setlocal

set "REPO_PATH=D:\2026 Projects\Nairobi-stock-Exchange"
set "LOG_DIR=%REPO_PATH%\logs"
set "LOG_FILE=%LOG_DIR%\weekly_task_scheduler.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] Starting weekly pipeline >> "%LOG_FILE%"
cd /d "%REPO_PATH%"
uv run nse-analysis generate-weekly-report >> "%LOG_FILE%" 2>&1
echo [%date% %time%] Weekly pipeline finished >> "%LOG_FILE%"

REM Commit and push if git is available
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] Committing weekly report >> "%LOG_FILE%"
    git add reports/weekly/*.md >> "%LOG_FILE%" 2>&1
    git diff --cached --quiet reports/weekly/*.md
    if %ERRORLEVEL% NEQ 0 (
        REM There are staged changes, commit and push
        git config user.name "NSE-Report-Bot" >> "%LOG_FILE%" 2>&1
        git config user.email "nse-report-bot@localhost" >> "%LOG_FILE%" 2>&1
        git commit -m "chore: add weekly NSE report" >> "%LOG_FILE%" 2>&1
        git push >> "%LOG_FILE%" 2>&1
        echo [%date% %time%] Weekly report committed and pushed >> "%LOG_FILE%"
    ) else (
        echo [%date% %time%] No changes to commit >> "%LOG_FILE%"
    )
)

endlocal
