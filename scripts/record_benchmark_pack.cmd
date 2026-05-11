@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%record_benchmark_pack.ps1" %*
exit /b %ERRORLEVEL%
