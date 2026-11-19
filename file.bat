
@echo off
setlocal

REM ==========================================
REM CONFIGURACION
REM ==========================================

title Script Automation
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "SCRIPT=local\extraer_local.py"

echo.
echo ==========================================
echo       PYTHON AUTOMATION SYSTEM
echo ==========================================
echo.

REM ==========================================
REM VALIDAR ENTORNO
REM ==========================================

if not exist "%PYTHON%" (
    echo [ERROR] No se encontro el entorno virtual.
    echo Ejecuta la configuracion del proyecto.
    pause
    exit /b 1
)

REM ==========================================
REM VALIDAR SCRIPT
REM ==========================================

if not exist "%SCRIPT%" (
    echo [ERROR] No se encontro el script principal.
    pause
    exit /b 1
)

REM ==========================================
REM EJECUCION
REM ==========================================

echo [INFO] Iniciando automatizacion...
echo.

"%PYTHON%" "%SCRIPT%"

set "EXIT_CODE=%ERRORLEVEL%"

REM ==========================================
REM RESULTADO
REM ==========================================

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] La automatizacion fallo.
    echo Codigo de salida: %EXIT_CODE%
    pause
    exit /b %EXIT_CODE%
)

echo.
echo [SUCCESS] Proceso finalizado correctamente.

pause
exit /b 0
