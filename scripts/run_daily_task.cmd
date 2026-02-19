@echo off
setlocal

set "REPO_PATH=D:\2026 Projects\Nairobi-stock-Exchange"
set "LOG_DIR=%REPO_PATH%\logs"
set "LOG_FILE=%LOG_DIR%\task_scheduler.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] Starting daily pipeline >> "%LOG_FILE%"
cd /d "%REPO_PATH%"
uv run nse-analysis run-daily >> "%LOG_FILE%" 2>&1
echo [%date% %time%] Daily pipeline finished >> "%LOG_FILE%"

endlocal
