@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "HOST=127.0.0.1"
set "PORT=8000"

echo ==========================================
echo   АИС "Витрина ИТ-проектов" - запуск
echo ==========================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python не найден.
  echo Установите Python 3.10 или новее: https://www.python.org/downloads/
  echo При установке отметьте пункт "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Требуется Python 3.10 или новее. Установлена версия:
  %PY% --version
  echo.
  pause
  exit /b 1
)

echo Приложение будет доступно по адресу: http://127.0.0.1:%PORT%
echo Браузер откроется автоматически. Не закрывайте это окно.
echo Для остановки нажмите Ctrl+C.
echo.

start "" cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:%PORT%"
%PY% app.py

echo.
echo Сервер остановлен.
pause
