@echo off
cd /d "%~dp0"

if not exist config.json (
    echo No config.json found, copying from config.example.json...
    copy config.example.json config.json
    echo.
    echo Please edit config.json to set your claude_path, then run this script again.
    pause
    exit /b 0
)

echo Registering redpaper startup task...
schtasks /create /tn "redpaper" /tr "pythonw \"%~dp0main.py\"" /sc onlogon /ru "%USERDOMAIN%\%USERNAME%" /f /delay 0000:30
if %errorlevel% neq 0 (
    echo Failed to register task.
    pause
    exit /b 1
)

echo Starting redpaper now...
start "" pythonw "%~dp0main.py"

for /f "tokens=2 delims=:, " %%p in ('findstr /i "web_port" config.json') do set PORT=%%p
if "%PORT%"=="" set PORT=18080

echo.
echo Done! redpaper is running at http://127.0.0.1:%PORT%
echo It will start automatically each time you log in.
echo Logs are written to %~dp0server.log
pause
