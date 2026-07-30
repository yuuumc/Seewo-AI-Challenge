@echo off
title 希沃智教Pi Demo

echo.
echo ============================================================
echo     Seewo AI Grading Pi -- Homework Grading System Demo
echo ============================================================
echo.

REM MIG-02: 显式开启 demo 模式（绕过 CSRF / 鉴权 / 限流），便于本地演示
set DEMO_AUTH_OPEN=1

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

pip install flask -q 2>nul

echo   Teacher  : http://localhost:5000/teacher
echo   Student  : http://localhost:5000/student/s02/dashboard
echo   Analytics: http://localhost:5000/teacher/analytics/hw_001
echo ============================================================
echo   Starting server...
echo   Press Ctrl+C to stop, then refresh browser.
echo ============================================================
echo.

:: Open browser, then start server (browser will connect once server is up)
start http://localhost:5000
python app.py
pause
