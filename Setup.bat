@echo off
rem Hi3D Studio setup: installs ComfyUI, the nodes and ~33 GB of models into this folder.
rem Needs: Windows 10/11, an NVIDIA GPU (16 GB+ recommended), Git for Windows (it brings Git Bash).
cd /d "%~dp0"
set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not exist "%BASH%" (
  echo Git for Windows was not found. Install it from https://git-scm.com/download/win and run this again.
  pause
  exit /b 1
)
"%BASH%" "%~dp0setup\install.sh"
pause
