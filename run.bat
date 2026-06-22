@echo off
chcp 936 >nul
cd /d "%~dp0"

echo [CF IP Tester] 清理旧缓存...
if exist ".cache" rmdir /s /q ".cache" 2>nul

echo [CF IP Tester] 启动中...
uv run main.py
pause
