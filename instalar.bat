@echo off
chcp 65001 >nul
title CinnaParleys - Instalación
cd /d "%~dp0"

echo [1/5] Creando entorno de Python 3.12...
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv || python -m venv .venv
)
echo [2/5] Instalando librerías de Python...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo [3/5] Instalando la interfaz web...
cd web
call npm install
call npm run build
cd ..

echo [4/5] Descargando historia 2016-hoy y entrenando modelos (tarda unos minutos)...
.venv\Scripts\python.exe -m scripts.entrenar

echo [5/5] Conectando el asistente de Claude (.mcp.json)...
.venv\Scripts\python.exe scripts\crear_mcp.py

echo.
echo Instalación completa. Ahora abre iniciar.bat
pause
