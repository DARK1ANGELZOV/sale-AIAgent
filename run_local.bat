@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating virtual environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :fail
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

python -c "import fastapi, qdrant_client, fastembed, llama_cpp, structlog" >nul 2>&1
if errorlevel 1 (
  echo [setup] Installing dependencies...
  python -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
)

echo.
echo Service URL:  http://127.0.0.1:8010
echo Web UI:       http://127.0.0.1:8010/
echo API Docs:     http://127.0.0.1:8010/docs
echo.
echo Press Ctrl+C to stop.
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
goto :eof

:fail
echo [error] Failed to start service.
exit /b 1
