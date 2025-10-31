@echo off
REM Общий скрипт для запуска API + Cloudflare Tunnel
REM Используется обоими start_api_dev.bat и start_api_prod.bat

if "%1"=="" (
    echo Error: No server type specified
    exit /b 1
)

set SERVER_TYPE=%1
set USE_WAITRESS=false
set SERVER_NAME=Flask Development

if "%SERVER_TYPE%"=="waitress" (
    set USE_WAITRESS=true
    set SERVER_NAME=Waitress Production
)

echo ============================================================
echo Starting ASTRAL AI API Server - %SERVER_NAME%
echo ============================================================
echo.

REM Переходим в директорию скрипта
cd /d %~dp0

REM Cloudflare Tunnel всегда использует локальный хост
set FLASK_HOST=127.0.0.1
set PYTHONUNBUFFERED=1

REM Создаем временный bat файл для запуска API с правильными переменными
set TEMP_BAT=%TEMP%\astral_api_start_%RANDOM%.bat
(
    echo @echo off
    echo cd /d %~dp0
    echo set USE_WAITRESS=%USE_WAITRESS%
    echo set FLASK_HOST=%FLASK_HOST%
    echo set PYTHONUNBUFFERED=1
    echo python api\index.py
) > "%TEMP_BAT%"

REM Start API server in background
start "ASTRAL API Server" cmd /k ""%TEMP_BAT%""

REM Wait for server to start
if "%USE_WAITRESS%"=="true" (
    echo Waiting 5 seconds for Waitress to start...
    timeout /t 5 /nobreak >nul
) else (
    echo Waiting 3 seconds for Flask to start...
    timeout /t 3 /nobreak >nul
)

REM Start Cloudflare Tunnel
echo Starting Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k cloudflared tunnel --url http://localhost:5000

echo.
echo ============================================================
echo API Server and Cloudflare Tunnel started!
echo.
echo Server: http://localhost:5000
echo Mode: %SERVER_NAME%
echo.
echo Public URL will be shown in the Cloudflare Tunnel window
echo Look for: "https://xxxxx.trycloudflare.com"
echo ============================================================
