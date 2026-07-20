# Script para iniciar el servidor Django y jugar BINGO
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "🎮 ============================================" -ForegroundColor Cyan
Write-Host "   INICIANDO SERVIDOR BINGO" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".\manage.py")) {
    Write-Host "❌ Error: No se encontró manage.py" -ForegroundColor Red
    exit 1
}

$venvPython = Join-Path $scriptDir '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
    Write-Host "🐍 Usando Python de entorno virtual: $pythonExe" -ForegroundColor Green
} else {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) {
        Write-Host "❌ No se encontró Python en el PATH ni en .venv" -ForegroundColor Red
        exit 1
    }
    Write-Host "🐍 Usando Python global: $pythonExe" -ForegroundColor Yellow
}

function Find-FreePort {
    param([int]$StartPort = 8000, [int]$MaxPort = 8100)

    for ($candidate = $StartPort; $candidate -le $MaxPort; $candidate++) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
            $listener.Start()
            return $candidate
        }
        catch {
            continue
        }
        finally {
            if ($listener) { $listener.Stop() }
        }
    }

    throw "No se encontró un puerto libre entre $StartPort y $MaxPort"
}

$port = Find-FreePort

Write-Host "🗄️  Aplicando migraciones..." -ForegroundColor Yellow
& $pythonExe manage.py migrate --run-syncdb 2>&1 | Out-Null

Write-Host "🔧 Cargando datos base de prueba..." -ForegroundColor Yellow
$env:DJANGO_SETTINGS_MODULE = 'bingo_prueba.settings'
& $pythonExe -c "import os, django, runpy; os.environ.setdefault('DJANGO_SETTINGS_MODULE','bingo_prueba.settings'); django.setup(); runpy.run_path('init_test_data.py')" 2>&1 | Out-Null

Write-Host "✅ Verificando sistema..." -ForegroundColor Yellow
$checkResult = & $pythonExe manage.py check 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errores encontrados:" -ForegroundColor Red
    Write-Host $checkResult
    exit 1
}

Write-Host ""
Write-Host "🚀 ============================================" -ForegroundColor Green
Write-Host "   SERVIDOR INICIADO CORRECTAMENTE" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "🌐 Accede a: http://localhost:$port/" -ForegroundColor Cyan
Write-Host ""
Write-Host "🔌 Presiona Ctrl+C para detener el servidor" -ForegroundColor Yellow
Write-Host ""

& $pythonExe manage.py runserver 0.0.0.0:$port
