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

:: Remove old Windows service if present
sc query redpaper >nul 2>&1
if %errorlevel% equ 0 (
    echo Removing old redpaper Windows service...
    net stop redpaper >nul 2>&1
    python service.py remove >nul 2>&1
)

echo Registering redpaper startup task...
schtasks /create /tn "redpaper" /tr "\"%PYTHONW%\" \"%~dp0main.py\"" /sc onlogon /ru "%USERDOMAIN%\%USERNAME%" /f /delay 0000:30
if %errorlevel% neq 0 (
    echo Failed to register startup task.
    pause
    exit /b 1
)

echo Starting redpaper now...
start "" "%PYTHONW%" "%~dp0main.py"

:: Wait for server to start (launcher waits for drive, then starts python)
echo Waiting for server to start...
timeout /t 15 /nobreak >nul

for /f "tokens=2 delims=:, " %%p in ('findstr /i "web_port" config.json') do set PORT=%%p
if "%PORT%"=="" set PORT=18080

powershell -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/' -UseBasicParsing -TimeoutSec 10 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo Done! redpaper is running at http://127.0.0.1:%PORT%
    echo It will start automatically each time you log in.
    echo Logs are written to %~dp0server.log
) else (
    echo.
    echo WARNING: redpaper does not seem to be responding on port %PORT%.
    echo Check %~dp0server.log for errors, or run: python main.py
)
pause
