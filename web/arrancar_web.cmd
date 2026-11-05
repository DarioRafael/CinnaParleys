@echo off
rem Interfaz de CinnaParleys: recompila sólo si hay cambios y la arranca (lo lanza iniciar_oculto.vbs, sin ventana).
cd /d "%~dp0"
set NEED_BUILD=0
if not exist ".next\BUILD_ID" set NEED_BUILD=1
if "%NEED_BUILD%"=="0" (
  powershell -NoProfile -Command "$b=(Get-Item '.next\BUILD_ID').LastWriteTime; if (Get-ChildItem app,components,lib -Recurse -File | Where-Object { $_.LastWriteTime -gt $b } | Select-Object -First 1) { exit 1 } else { exit 0 }"
  if errorlevel 1 set NEED_BUILD=1
)
if "%NEED_BUILD%"=="1" call npm run build
npx next start -p 3100
