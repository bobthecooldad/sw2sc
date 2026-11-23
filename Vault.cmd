@echo off
rem Opens the sw2sc vault window in your browser. Keep this window open while you use it.
cd /d "%~dp0"
python -m sw2sc gui
if errorlevel 1 pause
