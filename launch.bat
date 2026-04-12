@echo off
cd /d "%~dp0"
python "%~dp0main.py" >> "%~dp0server.log" 2>&1
