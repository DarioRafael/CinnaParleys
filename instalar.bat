@echo off
chcp 65001 >nul
setlocal
title CinnaParleys - Instalación
cd /d "%~dp0"

echo.
echo  ===============================================
echo    CinnaParleys - instalación en esta computadora
echo  ===============================================
echo.

rem ---------------------------------------------------------------- 1. requisitos
echo [1/6] Revisando Python 3.12 y Node.js...
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (
  python --version 2>nul | findstr /b /c:"Python 3.12" >nul && set "PY=python"
)
set "FALTA=0"
if not defined PY (
  echo    Falta Python 3.12.
  set "FALTA=1"
  call :instalar Python.Python.3.12 "Python 3.12"
)
node --version >nul 2>&1
if errorlevel 1 (
  echo    Falta Node.js.
  set "FALTA=1"
  call :instalar OpenJS.NodeJS.LTS "Node.js"
)
if "%FALTA%"=="1" (
  echo.
  echo    Cierra esta ventana y vuelve a abrir instalar.bat para continuar
  echo    ^(Windows necesita una ventana nueva para encontrar lo que se acaba de instalar^).
  pause
  exit /b 1
)
for /f "delims=" %%v in ('node --version') do echo    Node.js %%v
%PY% --version

rem ---------------------------------------------------------------- 2. entorno de Python
echo.
echo [2/6] Creando el entorno de Python...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || goto :error
)

echo.
echo [3/6] Instalando librerías de Python ^(unos minutos^)...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error

rem ---------------------------------------------------------------- 3. interfaz web
echo.
echo [4/6] Instalando y compilando la interfaz web...
pushd web
call npm ci || call npm install || (popd & goto :error)
call npm run build || (popd & goto :error)
popd

rem ---------------------------------------------------------------- 4. datos y modelos
echo.
echo [5/6] Descargando la historia de la NFL ^(2016 a hoy^) y preparando a Cinna.
echo       La primera vez tarda un buen rato: deja la ventana abierta.
.venv\Scripts\python.exe -m scripts.entrenar || goto :error

rem ---------------------------------------------------------------- 5. asistente de Claude
echo.
echo [6/6] Conectando el asistente de Claude ^(.mcp.json^)...
.venv\Scripts\python.exe scripts\crear_mcp.py || goto :error

echo.
echo  ===============================================
echo    Instalación completa.
echo  ===============================================
echo    1. Abre iniciar.bat ^(se abre http://localhost:3100^).
echo    2. Para las líneas reales de Playdoit: en la app ve a
echo       "Conectar Playdoit" y sigue los pasos para agregar la extensión.
echo.
pause
exit /b 0

rem ---------------------------------------------------------------- ayudantes
:instalar
rem %1 = id de winget, %2 = nombre para mostrar
winget --version >nul 2>&1
if errorlevel 1 (
  echo    Descarga e instala %~2 de su página oficial:
  echo      Python 3.12: https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
  echo      Node.js:     https://nodejs.org/  ^(versión LTS^)
  exit /b 0
)
choice /c SN /m "   ¿Lo instalo ahora con winget (el instalador oficial de Windows)?"
if errorlevel 2 (
  echo    Instálalo a mano y vuelve a abrir instalar.bat.
  exit /b 0
)
winget install -e --id %~1 --accept-package-agreements --accept-source-agreements
exit /b 0

:error
echo.
echo  *** Algo falló en el paso de arriba. ***
echo  Revisa tu conexión a internet y vuelve a abrir instalar.bat
echo  ^(lo que ya quedó instalado no se repite^).
pause
exit /b 1
