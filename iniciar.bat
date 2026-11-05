@echo off
rem Arranca CinnaParleys en segundo plano (sin terminales). Para apagarlo: detener.bat
cd /d "%~dp0"
start "" wscript.exe "%~dp0iniciar_oculto.vbs"
exit
