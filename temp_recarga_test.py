import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bingo_prueba.settings')
django.setup()
from django.test import Client
from django.contrib.auth.models import User
from bingo.models import Jugador

user, created = User.objects.get_or_create(username='jugador1', defaults={'email':'jugador@test.local'})
if created or not user.has_usable_password():
    user.set_password('jugador1')
    user.save()

jugador, _ = Jugador.objects.get_or_create(
    cedulaidentidadjugador='12345678',
    defaults={
        'aliasjugador':'Jugador Prueba',
        'nombresjugador':'Jugador',
        'apellidosjugador':'Prueba',
        'correojugador':'jugador@test.local',
        'saldocreditojugador':5000,
    }
)

from django.contrib.auth import authenticate

client = Client()
user = authenticate(username='jugador1', password='jugador1')
assert user is not None, 'AUTH FAILED'
client.force_login(user)
resp = client.get('/recargar-saldo/')
print('GET status:', resp.status_code)
print('GET redirected:', resp.url if resp.status_code in (301,302) else 'no')
print('GET contains recargar:', 'Recargar' in resp.content.decode('utf-8', errors='ignore'))

resp2 = client.post('/api/recargar-saldo/', data=json.dumps({'monto':'50'}), content_type='application/json')
print('POST status:', resp2.status_code)
print('POST body:', resp2.content.decode('utf-8', errors='ignore'))
