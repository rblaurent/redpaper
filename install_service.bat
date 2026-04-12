@echo off
echo Installing redpaper Windows Service...
cd /d "%~dp0"
python service.py install
if %errorlevel% neq 0 (
    echo Failed to install service. Make sure you are running as Administrator.
    pause
    exit /b 1
)
echo Starting redpaper service...
net start redpaper
echo.
echo Done! redpaper is running at http://127.0.0.1:8080
pause
