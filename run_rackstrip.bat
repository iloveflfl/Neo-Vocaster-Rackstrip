@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo Neo Vocaster RackStrip FIXED6 - Run
echo ============================================================
py -m pip install -r requirements.txt
py neo_vocaster_rackstrip.py
pause
