@echo off
set PORT=8099
echo ========================================
echo Starting DMS Instance Monitor
echo ========================================
cd /d "%~dp0"
cd backend
echo.
echo [1/2] Checking dependencies...
python -m pip install -r requirements.txt
echo.
echo [2/2] Launching server on http://localhost:%PORT%...
echo (You can close this window to stop the server)
start "" "http://localhost:%PORT%"
python -m uvicorn main:app --host 0.0.0.0 --port %PORT%
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to start server. Make sure Python is installed and port %PORT% is free.
    pause
)
