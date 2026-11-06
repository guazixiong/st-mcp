@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ST-MCP
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-server.ps1"
echo.
echo ST-MCP stopped. Press any key to close.
pause >nul
