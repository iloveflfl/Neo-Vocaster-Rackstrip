@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo Neo Vocaster RackStrip FIXED8 - Build Portable ONEFILE EXE
echo ============================================================
echo.

if not exist "neo_vocaster_rackstrip.py" (
    echo ERROR: neo_vocaster_rackstrip.py not found.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt not found.
    pause
    exit /b 1
)

if not exist "icon.ico" (
    echo ERROR: icon.ico not found.
    echo Put a real multi-size ICO file named icon.ico in this folder.
    pause
    exit /b 1
)

echo [1/7] Installing requirements...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install requirements failed.
    pause
    exit /b 1
)

echo.
echo [2/7] Installing Pillow for icon validation...
py -m pip install pillow
if errorlevel 1 (
    echo.
    echo ERROR: Pillow install failed.
    pause
    exit /b 1
)

echo.
echo [3/7] Validating icon.ico...
py -c "from PIL import Image; img=Image.open('icon.ico'); print('ICON:', img.format, img.size, 'frames=', getattr(img,'n_frames',1)); print('SIZES:', getattr(img,'ico',None).sizes() if hasattr(img,'ico') else 'n/a')"
if errorlevel 1 (
    echo.
    echo ERROR: icon.ico is not a valid ICO file.
    pause
    exit /b 1
)

echo.
echo [4/7] Rebuilding icon.ico as multi-size ICO for Windows shell stability...
py -c "from PIL import Image; img=Image.open('icon.ico').convert('RGBA'); img.save('icon_multi.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if errorlevel 1 (
    echo.
    echo ERROR: failed to rebuild icon.ico.
    pause
    exit /b 1
)
move /y "icon_multi.ico" "icon.ico" >nul

echo.
echo [5/7] Cleaning old build files...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "NeoVocasterRackStrip.spec" del /q "NeoVocasterRackStrip.spec"
if exist "NeoVocasterRackStrip_v8.spec" del /q "NeoVocasterRackStrip_v8.spec"
if exist "__pycache__" rmdir /s /q "__pycache__"

echo.
echo [6/7] Building portable EXE with EXE icon and Tkinter runtime icon...
py -m PyInstaller --noconsole --onefile --clean --name "NeoVocasterRackStrip_v8" --icon "%CD%\icon.ico" --add-data "icon.ico;." "neo_vocaster_rackstrip.py"

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check the error above.
    pause
    exit /b 1
)

echo.
echo [7/7] Build complete.
echo.
echo Output:
echo dist\NeoVocasterRackStrip_v8.exe
echo.
echo Notes:
echo - Explorer EXE icon uses --icon.
echo - Running window/taskbar icon uses iconbitmap plus --add-data.
echo - If Explorer still shows an old icon, rename the EXE or clear Windows icon cache.
echo.

pause
