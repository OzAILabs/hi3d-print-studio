@echo off
rem Hi3D Print Studio: web front end for picture -> detailed 3D -> Bambu colour print.
rem Starts the studio (which starts its own ComfyUI engine in the background) and opens the browser.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7870/api/status -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo Hi3D Print Studio is already running.
  start "" http://127.0.0.1:7870
  exit /b 0
)
start "" /min cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:7870"
"%~dp0ComfyUI_py312\python_embeded\python.exe" -s "%~dp0studio\server.py"
pause
