@echo off
setlocal

set "LAUNCHER=%~dp0launch_blender_analysis.ps1"

if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -Port 65433
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -Port 65433 -BlendFile "%~f1"
)

if errorlevel 1 (
    echo.
    echo Nao foi possivel abrir o Blender de analise.
    pause
)

endlocal
