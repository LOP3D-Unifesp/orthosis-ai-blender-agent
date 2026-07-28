@echo off
REM Atalho para gravar um marco da sessao de scan.
REM Uso:  tools\marco "o que acabei de fazer" [--criterio "por que"] [--render Objeto]
setlocal
cd /d "%~dp0.."
python tools\sessao_scan.py marco %*
endlocal
