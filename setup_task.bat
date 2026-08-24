@echo off
chcp 65001 > nul
echo =======================================================
echo     CONFIGURANDO TAREA PROGRAMADA DE WINDOWS (CRON)
echo =======================================================
echo.

:: Obtener la ruta del script scraper.py en el mismo directorio
set SCRIPT_PATH=%~dp0scraper.py

:: Intentar crear la tarea programada en Windows
schtasks /create /f /tn "BusquedaInmueblesSemanales" /tr "python.exe \"%SCRIPT_PATH%\"" /sc weekly /d TUE /st 11:00

if %errorlevel% equ 0 (
    echo.
    echo [OK] ¡Éxito! La tarea "BusquedaInmueblesSemanales" se registró correctamente.
    echo Se ejecutará todos los martes a las 11:00 AM de forma totalmente autónoma.
    echo (No requiere que Antigravity ni tu editor de código estén abiertos).
) else (
    echo.
    echo [ERROR] No se pudo registrar la tarea en Windows Task Scheduler.
    echo Por favor, haz clic derecho sobre este archivo "setup_task.bat" y selecciona "Ejecutar como Administrador".
)
echo.
pause
