@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ST-MCP verify
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify.ps1"
echo.
echo Press any key to close.
pause >nul
