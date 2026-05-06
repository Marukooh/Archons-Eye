@echo off
echo Building Archon's Eye single-file executable...
echo.

REM Clean previous builds
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM Build with PyInstaller using the spec file (onefile mode defined in spec)
python -m PyInstaller --clean --noconfirm archons_eye.spec

if errorlevel 1 (
    echo.
    echo Build failed with error %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo Build successful! Output: dist\Archon's Eye.exe
echo The executable is standalone and does not require Python to be installed.
pause
