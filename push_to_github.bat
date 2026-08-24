@echo off
chcp 65001 > nul
echo =======================================================
echo     PUBLICANDO WEB EN GITHUB PAGES (bungaleti)
echo =======================================================
echo.

set /p TOKEN="Introduce tu Personal Access Token (PAT) de GitHub: "

if "%TOKEN%"=="" (
    echo [ERROR] No introdujiste ningún token.
    pause
    exit /b 1
)

git remote set-url origin https://%TOKEN%@github.com/ozonito/bungaleti.git
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo [¡ÉXITO!] Tu web se ha publicado en GitHub.
    echo Ahora ve a https://github.com/ozonito/bungaleti/settings/pages
    echo y selecciona Source: "Deploy from a branch" -> Branch: "main" / (root).
) else (
    echo.
    echo [ERROR] No se pudo hacer el push. Comprueba que el repositorio "bungaleti" existe en tu cuenta de GitHub.
)
echo.
pause
