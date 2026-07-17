"""
Script para crear datos de prueba en BINGO
Ejecutar: python manage.py shell < init_test_data.py
"""

from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import json
import random

from bingo.models import (
    UnidadMonetaria, ConfiguracionWeb, Bingo, PartidaBingo, Jugador, 
    Carton, CartonPartidaBingo
)

print("🎮 Inicializando datos de prueba para BINGO...")

# 1. Crear Unidad Monetaria
moneda, created = UnidadMonetaria.objects.get_or_create(
    nombre='Efectivo',
    defaults={'simbolo': '$'}
)
print(f"✅ Moneda: {moneda.nombre}" if created else f"✅ Moneda existente: {moneda.nombre}")

# 2. Crear Admin
admin_user, created = User.objects.get_or_create(
    username='admin',
    defaults={
        'email': 'admin@bingo.local',
        'is_staff': True,
        'is_superuser': True
    }
)
if created:
    admin_user.set_password('admin')
    admin_user.save()
    print("✅ Admin creado: admin / admin")
else:
    print("✅ Admin existente")

# 3. Crear Jugador de Prueba
jugador_user, _ = User.objects.get_or_create(
    username='jugador1',
    defaults={'email': 'jugador@test.local'}
)
if not jugador_user.has_usable_password():
    jugador_user.set_password('jugador1')
    jugador_user.save()

jugador, created = Jugador.objects.get_or_create(
    cedulaidentidadjugador='12345678',
    defaults={
        'aliasjugador': 'Jugador Prueba',
        'nombresjugador': 'Jugador',
        'apellidosjugador': 'Prueba',
        'correojugador': 'jugador@test.local',
        'saldocreditojugador': Decimal('5000.00'),
    }
)
if not created:
    jugador.saldocreditojugador = Decimal('5000.00')
    jugador.save()
print(f"✅ Jugador: {jugador.aliasjugador} (Saldo: {jugador.saldocreditojugador})")

# 4. Crear BINGO (Evento)
ahora = timezone.now()
hora_futura = ahora + timedelta(hours=1)

bingo, created = Bingo.objects.get_or_create(
    titulobingo='BINGO DE PRUEBA',
    defaults={
        'fechaprogramadabingo': hora_futura,
        'tipobingo': 'Virtual',
        'lugarbingo': '',
        'preciocarton': Decimal('50.00'),
        'premiomayor': Decimal('5000.00'),
        'descripcionpremiomayor': 'Gran premio de prueba',
        'descripcionpremios': 'Premios secundarios disponibles',
        'estadobingo': 'Programado',
        'idunidadmonetaria': moneda,
    }
)
print(f"✅ Bingo: {bingo.titulobingo}")

# 5. Crear Partida de Bingo
partida, created = PartidaBingo.objects.get_or_create(
    idbingo=bingo,
    idpartidabingo=1,
    defaults={
        'nombreronda': 'Ronda 1 de Prueba',
        'estadopartida': 'Programada',  # Will be changed to 'En Juego' by admin
        'modalidad_victoria': 'En Diagonal',
        'valorpremio': Decimal('1000.00'),
        'premiomaterial': 'Regalo de prueba',
        'horainicio': ahora,
        'bolascantadas': '',
        'ultimabola': 0,
    }
)
print(f"✅ Partida: {partida.nombreronda} (Estado: {partida.estadopartida})")

# 6. Crear Cartones
CARTONES_PARA_JUGAR = 10
cartones_creados = 0
for i in range(CARTONES_PARA_JUGAR):
    matriz = {
        'B': [random.randint(1, 15) for _ in range(5)],
        'I': [random.randint(16, 30) for _ in range(5)],
        'N': [random.randint(31, 45) for _ in range(5)],
        'G': [random.randint(46, 60) for _ in range(5)],
        'O': [random.randint(61, 75) for _ in range(5)],
    }
    
    carton_codigo = f"CARTON-{i+1:03d}"
    carton, created = Carton.objects.get_or_create(
        codigocarton=carton_codigo,
        defaults={
            'matriznumeros': json.dumps(matriz),
            'esmaestro': False,
            'indicevictoria': random.randint(0, 100),
        }
    )
    
    if created:
        cartones_creados += 1
    
    # Asignar cartón a partida y jugador
    asignacion, _ = CartonPartidaBingo.objects.get_or_create(
        idcarton=carton,
        idpartida=partida,
        idjugador=jugador,
        defaults={
            'estadocarton': 'Vendido',
            'fechacompra': ahora,
            'preciopagado': bingo.preciocarton,
        }
    )

print(f"✅ Cartones creados: {cartones_creados}")

print("")
print("=" * 60)
print("🎉 DATOS DE PRUEBA INICIALIZADOS CORRECTAMENTE")
print("=" * 60)
print("")
print("📝 Credenciales:")
print("  Admin:    usuario=admin, contraseña=admin")
print("  Jugador:  usuario=jugador1, contraseña=jugador1")
print("")
print("🎮 Para jugar:")
print(f"  1. Login como admin")
print(f"  2. Ve al Dashboard")
print(f"  3. Haz clic en 'Tablero Admin' para la partida #{partida.idpartidabingo}")
print(f"  4. Haz clic en 'Iniciar Partida'")
print(f"  5. En otra pestaña, login como jugador1")
print(f"  6. Haz clic en 'Jugar Ahora' → 'ENTRAR AL JUEGO'")
print(f"  7. Vuelve a la ventana admin y activa 'Piloto Automático'")
print(f"  8. ¡A jugar! Los números se sincronizan en tiempo real")
print("")
