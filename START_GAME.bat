@echo off
REM Script para iniciar el servidor BINGO con Daphne
REM Este archivo inicia todo automáticamente

echo.
echo ====================================================
echo.    INICIANDO SERVIDOR BINGO CON DAPHNE
echo.
echo ====================================================
echo.

REM Cambiar a la carpeta del proyecto
cd /d c:\Users\USUARIO\Desktop\BINGO

REM Activar venv
call venv\Scripts\activate.bat

REM Instalar dependencias si faltan
echo.
echo Verificando dependencias...
python -m pip install -q daphne channels 2>nul

REM Crear datos de prueba si no existen
echo Inicializando base de datos...
python manage.py migrate --run-syncdb >nul 2>&1

REM Verificar que todo esté bien
python manage.py check >nul 2>&1
if errorlevel 1 (
    echo ERROR: El proyecto tiene problemas
    python manage.py check
    pause
    exit /b 1
)

REM Crear datos de prueba
echo Creando datos de prueba...
python manage.py shell < init_test_data.py >nul 2>&1

echo.
echo ====================================================
echo.
echo  ✓ SERVIDOR INICIADO CORRECTAMENTE
echo.
echo  Accede a: http://localhost:8000/
echo.
echo  Credenciales de prueba:
echo    Admin:    admin / admin
echo    Jugador:  jugador1 / jugador1
echo.
echo  PASOS PARA JUGAR:
echo    1. Login como admin
echo    2. Ve al Dashboard
echo    3. Haz clic en 'Administrador - Tablero'
echo    4. Haz clic en 'Iniciar Partida'
echo    5. En otra pestaña, login como jugador1
echo    6. Haz clic en 'Jugar Ahora'
echo    7. Haz clic en 'ENTRAR AL JUEGO'
echo    8. Vuelve a admin y activa 'Piloto Automático'
echo.
echo  ¡Los números se sincronizan en tiempo real!
echo.
echo  Presiona Ctrl+C para detener
echo.
echo ====================================================
echo.

REM Iniciar Daphne
python -m daphne -b 0.0.0.0 -p 8000 bingo_prueba.asgi:application

pause
