@echo off
REM Start Sonalim ERP backend and frontend
REM This script kills any existing processes on ports 8000 and 5173, then starts fresh

setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0

echo.
echo ========================================
echo Sonalim ERP - Starting Services
echo ========================================
echo.

REM Kill any existing processes on port 8000 (backend)
echo Cleaning up port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Kill any existing processes on port 5173 (frontend)
echo Cleaning up port 5173...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5173"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Wait a moment for ports to be released
timeout /t 1 /nobreak

echo.
echo Starting backend server on port 8000...
start "Sonalim ERP - Backend" cmd /k "cd /d "%SCRIPT_DIR%" && .\.venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

REM Wait a moment for backend to start
timeout /t 3 /nobreak

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
echo.
echo Both servers are running in separate windows.
echo Monitor the console output to check server health.
echo.
timeout /t 3 /nobreak
