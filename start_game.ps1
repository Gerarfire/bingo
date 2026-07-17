# Script para iniciar el servidor Daphne y jugar BINGO
Write-Host "🎮 ============================================" -ForegroundColor Cyan
Write-Host "   INICIANDO SERVIDOR BINGO CON DAPHNE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si estamos en la carpeta correcta
if (-not (Test-Path ".\manage.py")) {
    Write-Host "❌ Error: No se encontró manage.py" -ForegroundColor Red
    Write-Host "   Ejecuta este script desde: c:\Users\USUARIO\Desktop\BINGO" -ForegroundColor Yellow
    exit 1
}

# Activar venv
Write-Host "📦 Activando ambiente virtual..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

# Verificar que Daphne está instalado
Write-Host "🔍 Verificando dependencias..." -ForegroundColor Yellow
$daphneCheck = & python -c "import daphne" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Daphne no está instalado. Instalando..." -ForegroundColor Yellow
    pip install daphne channels
}

# Migrations
Write-Host "🗄️  Aplicando migraciones..." -ForegroundColor Yellow
python manage.py migrate --run-syncdb 2>&1 | Out-Null

# Verificar integridad
Write-Host "✅ Verificando sistema..." -ForegroundColor Yellow
$checkResult = python manage.py check 2>&1
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
Write-Host "🌐 Accede a: http://localhost:8000/" -ForegroundColor Cyan
Write-Host ""
Write-Host "📝 Instrucciones para jugar:" -ForegroundColor Cyan
Write-Host "  1. Login como admin (staff=true en DB)" -ForegroundColor White
Write-Host "  2. Ve a Dashboard → Crear/Ver Partidas" -ForegroundColor White
Write-Host "  3. Asigna cartones a jugadores" -ForegroundColor White
Write-Host "  4. Haz clic en 'Iniciar Partida'" -ForegroundColor White
Write-Host "  5. Ve a 'Consola de Administrador'" -ForegroundColor White
Write-Host "  6. Activa 'Piloto Automático' para sacar bolas cada 5s" -ForegroundColor White
Write-Host "  7. Los jugadores ven números sincronizados en tiempo real" -ForegroundColor White
Write-Host ""
Write-Host "⚙️  Opciones:" -ForegroundColor Cyan
Write-Host "  - Sacar bola manual: Botón 'SACAR SIGUIENTE BOLA'" -ForegroundColor White
Write-Host "  - Auto-marcado: Los jugadores habilitan en sus tableros" -ForegroundColor White
Write-Host "  - Desempate: Si hay múltiples ganadores, admin resuelve" -ForegroundColor White
Write-Host ""
Write-Host "🔌 Presiona Ctrl+C para detener el servidor" -ForegroundColor Yellow
Write-Host ""

# Iniciar Daphne
python -m daphne -b 0.0.0.0 -p 8000 bingo_prueba.asgi:application
