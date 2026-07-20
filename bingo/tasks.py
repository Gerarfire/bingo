import random
import time

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from .models import Carton, PartidaBingo
from .services import generar_lote_cartones


def _enviar_evento_partida(id_partida, datos):
    """Envía un evento a los clientes websocket si el canal está disponible."""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            f"bingo_partida_{id_partida}",
            {
                "type": "evento_partida",
                "datos": datos,
            },
        )
    except Exception:
        return


def avanzar_partida_con_bola(id_partida, enviar_evento=True):
    """Avanza una partida generando una bola nueva y persistiendo el estado."""
    partida = PartidaBingo.objects.get(idpartidabingo=id_partida)
    bolas = []
    if partida.bolascantadas:
        bolas = [
            int(x)
            for x in str(partida.bolascantadas).split(",")
            if str(x).strip().isdigit()
        ]

    disponibles = [i for i in range(1, 76) if i not in bolas]
    if not disponibles:
        partida.estadopartida = "Finalizada"
        partida.save()
        if enviar_evento:
            _enviar_evento_partida(
                id_partida, {"evento": "partida_finalizada"})
        return None

    nueva = random.choice(disponibles)
    bolas.append(nueva)
    partida.ultimabola = nueva
    partida.bolascantadas = ",".join(map(str, bolas))
    partida.save()

    if enviar_evento:
        _enviar_evento_partida(
            id_partida, {"evento": "nueva_bola", "numero": nueva})

    return nueva


@shared_task
def fabricar_cartones_maestros_task(cantidad):
    """
    Tarea asíncrona: fabrica cartones maestros en segundo plano y evita duplicados.
    """
    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return "Error en fábrica: la cantidad debe ser un número entero."

    if cantidad <= 0:
        return "Error en fábrica: la cantidad debe ser mayor que cero."

    try:
        lote = generar_lote_cartones(cantidad)
        if not lote:
            return f"No se generaron cartones para la cantidad solicitada ({cantidad})."

        with transaction.atomic():
            cartones_db = [
                Carton(
                    codigocarton=c['codigo'],
                    matriznumeros=c['matriz'],
                    esmaestro=True,
                ) for c in lote
            ]
            Carton.objects.bulk_create(cartones_db, ignore_conflicts=True)

        return f"Éxito: Se estamparon {len(lote)} cartones maestros."
    except Exception as e:
        return f"Error en fábrica: {str(e)}"


@shared_task
def sacar_bolas_task(id_partida):
    try:
        partida = PartidaBingo.objects.get(idpartidabingo=id_partida)

        while partida.estadopartida == "En Juego":
            nueva = avanzar_partida_con_bola(id_partida, enviar_evento=True)
            if nueva is None:
                break

            time.sleep(8)
            partida.refresh_from_db()

    except Exception as e:
        print(e)


@shared_task
def iniciar_partida_task(id_partida):
    try:
        partida = PartidaBingo.objects.get(idpartidabingo=id_partida)

        if partida.estadopartida != "Programada":
            return

        partida.estadopartida = "En Juego"
        partida.horainiciopartida = timezone.now()
        partida.save()

        _enviar_evento_partida(
            id_partida, {"evento": "estado_cambiado", "nuevo_estado": "En Juego"})

        sacar_bolas_task.delay(id_partida)

    except Exception as e:
        print(e)
