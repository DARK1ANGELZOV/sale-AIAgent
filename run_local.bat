@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Создаю виртуальное окружение...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :fail
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

python -c "import fastapi, qdrant_client, fastembed, llama_cpp, structlog" >nul 2>&1
if errorlevel 1 (
  echo [setup] Устанавливаю зависимости...
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
echo Нажмите Ctrl+C для остановки.
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
goto :eof

:fail
echo [error] Не удалось запустить сервис.
exit /b 1
