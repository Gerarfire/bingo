from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from . import tasks as tasks_module
from . import views as views_module
from .models import Bingo, Carton, CartonPartidaBingo, Jugador, PartidaBingo, UnidadMonetaria
from .services import evaluar_patron_victoria, generar_lote_cartones
from .tasks import avanzar_partida_con_bola, fabricar_cartones_maestros_task, iniciar_partida_task


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


class EvaluacionPatronesTest(TestCase):
    def test_patron_tabla_llena_reconoce_carton_completo(self):
        marcadas = set(range(25))
        self.assertTrue(evaluar_patron_victoria(marcadas, 'Tabla Llena'))

    def test_patron_esquinas_reconoce_cuatro_esquinas(self):
        marcadas = {0, 4, 20, 24}
        self.assertTrue(evaluar_patron_victoria(
            marcadas, 'Las Cuatro Esquinas'))


class FlujoCartonesTest(TestCase):
    def test_fabricar_cartones_maestros_task_crea_cartones(self):
        resultado = fabricar_cartones_maestros_task(2)

        self.assertIn('Éxito', resultado)
        self.assertEqual(Carton.objects.filter(esmaestro=True).count(), 2)

    def test_avanzar_partida_con_bola_genera_nueva_bola(self):
        unidad = UnidadMonetaria.objects.create(
            nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
        bingo = Bingo.objects.create(
            titulobingo='Bingo de prueba',
            fechaprogramadabingo=timezone.now(),
            tipobingo='Virtual',
            preciocarton='10.00',
            premiomayor='100.00',
            descripcionpremiomayor='Premio mayor',
            estadobingo='En Curso',
            idunidadmonetaria=unidad,
        )
        partida = PartidaBingo.objects.create(
            idbingo=bingo,
            nombreronda='Ronda 1',
            valorefectivo='25.00',
            premiomaterial='Ninguno',
            estadopartida='En Juego',
            bolascantadas='',
            ultimabola=0,
            horainicio=timezone.now(),
        )

        nueva_bola = avanzar_partida_con_bola(
            partida.idpartidabingo, enviar_evento=False)

        partida.refresh_from_db()
        self.assertTrue(nueva_bola >= 1 and nueva_bola <= 75)
        self.assertEqual(partida.ultimabola, nueva_bola)
        self.assertIn(str(nueva_bola), partida.bolascantadas)

    def test_iniciar_partida_task_cambia_estado_y_dispara_tarea(self):
        unidad = UnidadMonetaria.objects.create(
            nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
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

        with patch.object(tasks_module.sacar_bolas_task, 'delay') as mock_delay:
            iniciar_partida_task(partida.idpartidabingo)

        partida.refresh_from_db()
        self.assertEqual(partida.estadopartida, 'En Juego')
        self.assertIsNotNone(partida.horainiciopartida)
        mock_delay.assert_called_once_with(partida.idpartidabingo)

    def test_sacar_bola_api_permite_a_usuario_normal_avanzar_la_partida(self):
        unidad = UnidadMonetaria.objects.create(
            nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
        bingo = Bingo.objects.create(
            titulobingo='Bingo de prueba',
            fechaprogramadabingo=timezone.now(),
            tipobingo='Virtual',
            preciocarton='10.00',
            premiomayor='100.00',
            descripcionpremiomayor='Premio mayor',
            estadobingo='En Curso',
            idunidadmonetaria=unidad,
        )
        partida = PartidaBingo.objects.create(
            idbingo=bingo,
            nombreronda='Ronda 1',
            valorefectivo='25.00',
            premiomaterial='Ninguno',
            estadopartida='En Juego',
            bolascantadas='',
            ultimabola=0,
            horainicio=timezone.now(),
        )
        user = User.objects.create_user(username='jugador', password='secret')
        self.client.force_login(user)

        with patch.object(views_module, 'avanzar_partida_con_bola', return_value=11) as mock_avanzar, \
                patch.object(views_module, 'get_channel_layer', return_value=None):
            response = self.client.post(
                f'/api/partida/{partida.idpartidabingo}/sacar_bola/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['bola_extraida'], 11)
        mock_avanzar.assert_called_once_with(
            partida.idpartidabingo, enviar_evento=True)

    def test_sacar_bola_api_reutiliza_el_avance_compartido(self):
        unidad = UnidadMonetaria.objects.create(
            nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
        bingo = Bingo.objects.create(
            titulobingo='Bingo de prueba',
            fechaprogramadabingo=timezone.now(),
            tipobingo='Virtual',
            preciocarton='10.00',
            premiomayor='100.00',
            descripcionpremiomayor='Premio mayor',
            estadobingo='En Curso',
            idunidadmonetaria=unidad,
        )
        partida = PartidaBingo.objects.create(
            idbingo=bingo,
            nombreronda='Ronda 1',
            valorefectivo='25.00',
            premiomaterial='Ninguno',
            estadopartida='En Juego',
            bolascantadas='',
            ultimabola=0,
            horainicio=timezone.now(),
        )
        user = User.objects.create_user(
            username='admin', password='secret', is_staff=True)
        self.client.force_login(user)

        with patch.object(views_module, 'avanzar_partida_con_bola', return_value=7) as mock_avanzar, \
                patch.object(views_module, 'get_channel_layer', return_value=None):
            response = self.client.post(
                f'/api/partida/{partida.idpartidabingo}/sacar_bola/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['bola_extraida'], 7)
        mock_avanzar.assert_called_once_with(
            partida.idpartidabingo, enviar_evento=True)

    def test_procesar_recarga_saldo_acepta_datos_de_formulario(self):
        unidad = UnidadMonetaria.objects.create(
            nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
        bingo = Bingo.objects.create(
            titulobingo='Bingo de prueba',
            fechaprogramadabingo=timezone.now(),
            tipobingo='Virtual',
            preciocarton='10.00',
            premiomayor='100.00',
            descripcionpremiomayor='Premio mayor',
            estadobingo='En Curso',
            idunidadmonetaria=unidad,
        )
        partida = PartidaBingo.objects.create(
            idbingo=bingo,
            nombreronda='Ronda 1',
            valorefectivo='25.00',
            premiomaterial='Ninguno',
            estadopartida='En Juego',
            bolascantadas='',
            ultimabola=0,
            horainicio=timezone.now(),
        )
        jugador = Jugador.objects.create(
            aliasjugador='Recargador',
            cedulaidentidadjugador='1111111111',
            correojugador='recarga@example.com',
            saldocreditojugador='20.00',
        )
        user = User.objects.create_user(
            username='1111111111', password='secret')
        self.client.force_login(user)

        response = self.client.post('/api/recargar-saldo/', {'monto': '15.50'})

        self.assertEqual(response.status_code, 200)
        jugador.refresh_from_db()
        self.assertEqual(jugador.saldocreditojugador, Decimal('35.50'))

    def test_partida_expone_valorpremio_y_muestra_cartones(self):
        unidad = UnidadMonetaria.objects.create(
            nombremoneda='Dólares', simbolomoneda='$', tipomoneda='Efectivo')
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

        carton = Carton.objects.create(codigocarton='TEST-001', matriznumeros={'B': [1, 2, 3, 4, 5], 'I': [
                                       6, 7, 8, 9, 10], 'N': [11, 12, 13, 14, 15], 'G': [16, 17, 18, 19, 20], 'O': [21, 22, 23, 24, 25]})
        jugador = Jugador.objects.create(aliasjugador='TestUser', cedulaidentidadjugador='1234567890',
                                         correojugador='test@example.com', saldocreditojugador='100.00')
        CartonPartidaBingo.objects.create(
            idjugador=jugador, idpartida=partida, idcarton=carton, preciopagado='10.00', estadocarton='Vendido')

        user = User.objects.create_user(
            username='1234567890', password='secret')
        self.client.force_login(user)
        response = self.client.get('/mis-cartones/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TEST-001')

    def test_generar_lote_cartones_retorna_cartones_unicos(self):
        lote = generar_lote_cartones(2)

        self.assertEqual(len(lote), 2)
        self.assertTrue(
            all('codigo' in carton and 'matriz' in carton for carton in lote))
