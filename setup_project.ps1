# Script de instalación y arranque para Windows
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "==============================" -ForegroundColor Cyan
Write-Host "Configurando entorno de BINGO" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python no está disponible en PATH. Instálalo primero." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Yellow
    py -3 -m venv .venv
}

$pythonExe = Join-Path $scriptDir '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    Write-Host "❌ No se pudo localizar el intérprete de .venv" -ForegroundColor Red
    exit 1
}

Write-Host "Instalando dependencias..." -ForegroundColor Yellow
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r requirements.txt

Write-Host "Aplicando migraciones..." -ForegroundColor Yellow
& $pythonExe manage.py migrate --run-syncdb

Write-Host "Cargando datos de prueba..." -ForegroundColor Yellow
$env:DJANGO_SETTINGS_MODULE = 'bingo_prueba.settings'
& $pythonExe -c "import os, django, runpy; os.environ.setdefault('DJANGO_SETTINGS_MODULE','bingo_prueba.settings'); django.setup(); runpy.run_path('init_test_data.py')"

Write-Host "" 
Write-Host "✅ Proyecto listo para usar" -ForegroundColor Green
Write-Host "" 
Write-Host "Accede en tu navegador a: http://localhost:8000/" -ForegroundColor Cyan
Write-Host "Usuario administrador: admin / admin" -ForegroundColor Cyan
Write-Host "Usuario jugador: jugador1 / jugador1" -ForegroundColor Cyan
Write-Host "" 
Write-Host "Para iniciar el servidor después de la instalación ejecuta:" -ForegroundColor Yellow
Write-Host "  .\start_game.ps1" -ForegroundColor Yellow
