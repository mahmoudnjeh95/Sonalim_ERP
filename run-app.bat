@echo off
REM Start Sonalim ERP backend and frontend
REM This script kills any existing processes on ports 8000, 5173 and 8100, then starts fresh

setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0

echo.
echo ========================================
echo Sonalim ERP - Starting Services
echo ========================================
echo.

REM Kill any existing processes on port 8000 (backend)
echo Cleaning up port 8000...
REM Only listeners: a bare ":8000" also matches browsers connected to it. /T takes the process tree, and
REM --reload serves from a child of a reloader, so a python.exe parent is stopped too or it starts another.
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do (
    powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%%a'; if ($p) { $parent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $p.ParentProcessId); if ($parent -and $parent.Name -eq 'python.exe') { Stop-Process -Id $parent.ProcessId -Force } }" >nul 2>&1
    taskkill /F /T /PID %%a >nul 2>&1
)

REM Kill any existing processes on port 5173 (frontend)
echo Cleaning up port 5173...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5173" ^| find "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
)

REM Kill any existing processes on port 8100 (OCR service)
echo Cleaning up port 8100...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8100" ^| find "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
)

REM Wait a moment for ports to be released
timeout /t 1 /nobreak

echo.
echo Starting backend server on port 8000...
start "Sonalim ERP - Backend" cmd /k "cd /d "%SCRIPT_DIR%backend" && .\.venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

REM Wait a moment for backend to start
timeout /t 3 /nobreak

REM The OCR service reads the photographed shift fiches. It lives in its own venv
REM (ocr\.venv) so the heavy ONNX Runtime / OpenCV wheels stay out of the backend venv;
REM the first run creates it and installs them, which takes a few minutes.
if not exist "%SCRIPT_DIR%ocr\.venv\Scripts\python.exe" (
    echo.
    echo First run: creating the OCR virtual environment in ocr\.venv ...
    python -m venv "%SCRIPT_DIR%ocr\.venv"
    echo Installing OCR dependencies ^(this takes a few minutes^)...
    "%SCRIPT_DIR%ocr\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    "%SCRIPT_DIR%ocr\.venv\Scripts\python.exe" -m pip install -r "%SCRIPT_DIR%ocr\requirements.txt"
)

echo Starting OCR service on port 8100...
start "Sonalim ERP - OCR" cmd /k "cd /d "%SCRIPT_DIR%ocr" && set "PYTHONUTF8=1" && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100"

REM The reader hands queued photos to the OCR service. On the server this loop runs inside
REM the worker, which also needs RabbitMQ; locally it runs on its own so no broker is needed.
echo Starting scan reader...
start "Sonalim ERP - Scan Reader" cmd /k "cd /d "%SCRIPT_DIR%backend" && set "PYTHONUTF8=1" && .\.venv\Scripts\python.exe -m scripts.scan_reader"

echo Starting frontend dev server on port 5173...
start "Sonalim ERP - Frontend" cmd /k "cd /d "%SCRIPT_DIR%frontend" && npm run dev"

echo.
echo ========================================
echo Services Started Successfully!
echo ========================================
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo API Docs: http://localhost:8000/docs
echo OCR:      http://localhost:8100/health
echo.
echo All servers are running in separate windows.
echo Monitor the console output to check server health.
echo.
timeout /t 3 /nobreak
