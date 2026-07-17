from django.test import TestCase
from django.utils import timezone

from .models import Bingo, UnidadMonetaria


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
