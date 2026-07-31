@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AI Minecraft - Windows Setup
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python is not installed or not in PATH.
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js is not installed or not in PATH.
  pause
  exit /b 1
)

if exist ".git" (
  where git-lfs >nul 2>nul
  if not errorlevel 1 (
    echo Pulling trained best.pt from Git LFS...
    git lfs install
    git lfs pull
  )
)

echo Installing Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Installing Mineflayer...
call npm install
if errorlevel 1 goto :fail

echo.
echo Setup complete.
echo Start your Minecraft server, then run run_controller.bat
pause
exit /b 0

:fail
echo.
echo Setup failed. Check the error above.
pause
exit /b 1
