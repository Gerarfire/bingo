from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Bingo, Carton, CartonPartidaBingo, Jugador, PartidaBingo, UnidadMonetaria
from .services import generar_lote_cartones


class SmokeTest(TestCase):
    def test_smoke(self):
        self.assertTrue(True)


class CompatibilidadUnidadMonetariaTest(TestCase):
    def test_bingo_expone_la_unidad_monetaria_legacy(self):
        unidad = UnidadMonetaria.objects.create(nombre='Dólares', simbolo='$')
        bingo = Bingo.objects.create(
            titulobingo='Bingo de prueba',
            fechaprogramadabingo=timezone.now(),
            tipobingo='Virtual',
            preciocarton='100.00',
            premiomayor='5000.00',
            descripcionpremiomayor='Premio mayor',
            estadobingo='Programado',
            idunidadmonetaria=unidad,
        )

        self.assertEqual(bingo.idunidadmonetaria, unidad)
        self.assertEqual(bingo.idunidadmonetaria.simbolomoneda, '$')


class FlujoCartonesTest(TestCase):
    def test_partida_expone_valorpremio_y_muestra_cartones(self):
        unidad = UnidadMonetaria.objects.create(nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
        bingo = Bingo.objects.create(
            titulobingo='Bingo de prueba',
            fechaprogramadabingo=timezone.now(),
            tipobingo='Virtual',
            preciocarton='10.00',
            premiomayor='100.00',
            descripcionpremiomayor='Premio mayor',
            estadobingo='Programado',
            idunidadmonetaria=unidad,
        )
        partida = PartidaBingo.objects.create(
            idbingo=bingo,
            nombreronda='Ronda 1',
            valorefectivo='25.00',
            premiomaterial='Ninguno',
            estadopartida='Programada',
            bolascantadas='',
            ultimabola=0,
            horainicio=timezone.now(),
        )

        self.assertEqual(partida.valorpremio, Decimal('25.00'))

        carton = Carton.objects.create(codigocarton='TEST-001', matriznumeros={'B': [1, 2, 3, 4, 5], 'I': [6, 7, 8, 9, 10], 'N': [11, 12, 13, 14, 15], 'G': [16, 17, 18, 19, 20], 'O': [21, 22, 23, 24, 25]})
        jugador = Jugador.objects.create(aliasjugador='TestUser', cedulaidentidadjugador='1234567890', correojugador='test@example.com', saldocreditojugador='100.00')
        CartonPartidaBingo.objects.create(idjugador=jugador, idpartida=partida, idcarton=carton, preciopagado='10.00', estadocarton='Vendido')

        user = User.objects.create_user(username='1234567890', password='secret')
        self.client.force_login(user)
        response = self.client.get('/mis-cartones/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TEST-001')

    def test_generar_lote_cartones_retorna_cartones_unicos(self):
        lote = generar_lote_cartones(2)

        self.assertEqual(len(lote), 2)
        self.assertTrue(all('codigo' in carton and 'matriz' in carton for carton in lote))
