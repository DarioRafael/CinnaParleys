@echo off
rem Apaga CinnaParleys (API en el puerto 8765 e interfaz en el 3100).
powershell -NoProfile -Command "foreach($p in 8765,3100){ Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }"
echo CinnaParleys detenido.
timeout /t 2 >nul
