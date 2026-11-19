@echo off
setlocal

REM ==========================================
REM CONFIGURACION
REM ==========================================

title Extraccion de actas
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "SCRIPT=local\extraer_local.py"
set "TESSDATA=%~dp0tessdata"
set "WINGET=winget install -e --source winget --silent --accept-package-agreements --accept-source-agreements"

echo.
echo ==========================================
echo       EXTRACCION DE ACTAS
echo ==========================================
echo.

if not exist "%SCRIPT%" (
    echo [ERROR] No se encontro el script principal.
    goto :fallo
)

REM ==========================================
REM 1. PYTHON Y LIBRERIAS (solo la primera vez)
REM ==========================================

if exist ".venv\instalado.ok" goto :tesseract
echo [INFO] Primera ejecucion: instalando lo necesario. Puede tardar varios minutos.

if exist "%PYTHON%" goto :librerias
call :buscar_python
if not defined BASE_PY call :instalar_python
if not defined BASE_PY (
    echo [ERROR] No se pudo instalar Python. Instalalo desde python.org y vuelve a ejecutar.
    goto :fallo
)
echo [INFO] Creando entorno con %BASE_PY%
"%BASE_PY%" -m venv .venv
if not exist "%PYTHON%" (
    echo [ERROR] No se pudo crear el entorno virtual.
    goto :fallo
)

:librerias
echo [INFO] Instalando librerias...
"%PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de librerias. Revisa la conexion a internet.
    goto :fallo
)
REM Marca de instalacion completa: si falta, la siguiente ejecucion reintenta.
echo ok> ".venv\instalado.ok"

REM ==========================================
REM 2. TESSERACT OCR (opcional: sin el se omiten las actas escaneadas)
REM ==========================================

:tesseract
set "HAY_TESS="
if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "HAY_TESS=1"
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "HAY_TESS=1"
if defined HAY_TESS goto :idiomas
where winget >nul 2>nul
if errorlevel 1 goto :sin_tesseract
echo [INFO] Instalando Tesseract OCR (puede pedir permiso de administrador)...
%WINGET% --id UB-Mannheim.TesseractOCR
if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" goto :idiomas
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" goto :idiomas
:sin_tesseract
echo [AVISO] Tesseract no esta instalado: las actas escaneadas se omitiran.
goto :ejecutar

:idiomas
REM Idiomas en la carpeta del proyecto: no hace falta escribir en Program Files.
if not exist "%TESSDATA%\spa.traineddata" call :descargar spa
if not exist "%TESSDATA%\osd.traineddata" call :descargar osd
if exist "%TESSDATA%\spa.traineddata" if exist "%TESSDATA%\osd.traineddata" set "TESSDATA_PREFIX=%TESSDATA%"
if not defined TESSDATA_PREFIX echo [AVISO] No se pudo descargar el idioma espanol del OCR.

REM ==========================================
REM 3. EJECUCION
REM ==========================================

:ejecutar
echo [INFO] Iniciando extraccion...
echo.

"%PYTHON%" "%SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] La extraccion fallo. Codigo de salida: %EXIT_CODE%
    echo Revisa el archivo mas reciente en la carpeta logs.
    pause
    exit /b %EXIT_CODE%
)

echo.
echo [SUCCESS] Proceso finalizado correctamente.
pause
exit /b 0

:fallo
pause
exit /b 1

REM ==========================================
REM SUBRUTINAS
REM ==========================================

:buscar_python
REM Python 3.10+ ya instalado; se valida la ruta por si "python" es el acceso directo a la Microsoft Store.
set "BASE_PY="
for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable) if sys.version_info >= (3,10) else None" 2^>nul') do set "BASE_PY=%%i"
if defined BASE_PY if exist "%BASE_PY%" exit /b 0
set "BASE_PY="
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable) if sys.version_info >= (3,10) else None" 2^>nul') do set "BASE_PY=%%i"
if defined BASE_PY if exist "%BASE_PY%" exit /b 0
set "BASE_PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "BASE_PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
exit /b 0

:instalar_python
where winget >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Este equipo no tiene winget. Instala "App Installer" desde la Microsoft Store.
    exit /b 1
)
echo [INFO] Instalando Python 3.13...
%WINGET% --scope user --id Python.Python.3.13
call :buscar_python
exit /b 0

:descargar
if not exist "%TESSDATA%" mkdir "%TESSDATA%"
echo [INFO] Descargando idioma %1 del OCR...
curl -L -f -s -S -o "%TESSDATA%\%1.tmp" "https://github.com/tesseract-ocr/tessdata/raw/main/%1.traineddata"
if not errorlevel 1 move /y "%TESSDATA%\%1.tmp" "%TESSDATA%\%1.traineddata" >nul
exit /b 0
