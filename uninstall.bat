@echo off
echo Stopping redpaper...
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq redpaper" 2>nul

echo Removing startup task...
schtasks /delete /tn "redpaper" /f
if %errorlevel% neq 0 (
    echo Task not found or already removed.
)

echo Done.
pause
