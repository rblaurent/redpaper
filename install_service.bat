@echo off
cd /d "%~dp0"

if not exist config.json (
    echo No config.json found, copying from config.example.json...
    copy config.example.json config.json
    echo Please edit config.json to set your claude_path before continuing.
    pause
    exit /b 0
)

echo Installing redpaper Windows Service...
python service.py install
if %errorlevel% neq 0 (
    echo Failed to install service. Make sure you are running as Administrator.
    pause
    exit /b 1
)

echo Starting redpaper service...
net start redpaper
if %errorlevel% neq 0 (
    echo Failed to start service. Check Windows Event Viewer for details.
    pause
    exit /b 1
)

for /f "tokens=2 delims=:, " %%p in ('findstr /i "web_port" config.json') do set PORT=%%p
if "%PORT%"=="" set PORT=18080

echo.
echo Done! redpaper is running at http://127.0.0.1:%PORT%
pause
