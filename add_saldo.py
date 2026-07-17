#!/usr/bin/env python
"""
Script para agregar saldo a jugadores de prueba
Uso: python manage.py shell < add_saldo.py
"""

from decimal import Decimal
from bingo.models import Jugador

print("=" * 60)
print("AGREGANDO SALDO A JUGADORES")
print("=" * 60)

# Buscar todos los jugadores
jugadores = Jugador.objects.all()

if not jugadores.exists():
    print("❌ No hay jugadores en la base de datos")
    print("Primero ejecuta: python manage.py shell < init_test_data.py")
else:
    for jugador in jugadores:
        saldo_anterior = jugador.saldocreditojugador
        jugador.saldocreditojugador = Decimal('1000.00')
        jugador.save()
        print(f"✅ {jugador.aliasjugador}: ${saldo_anterior} → ${jugador.saldocreditojugador}")

print("=" * 60)
print("Proceso completado")
print("=" * 60)
