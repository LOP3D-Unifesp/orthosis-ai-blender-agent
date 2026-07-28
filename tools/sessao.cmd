@echo off
REM Atalho para os demais comandos da sessao de scan.
REM Uso:  tools\sessao inicio --paciente P01 --nota "equino grave, D"
REM       tools\sessao estado
REM       tools\sessao resumo
REM       tools\sessao fim
setlocal
cd /d "%~dp0.."
python tools\sessao_scan.py %*
endlocal
