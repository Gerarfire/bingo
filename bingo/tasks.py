import random
import re
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


def _crear_o_reusar_siguiente_partida(partida_actual):
    """Crea o reutiliza la siguiente ronda para mantener el flujo automático."""
    siguiente = PartidaBingo.objects.filter(
        idbingo=partida_actual.idbingo,
        idpartidabingo__gt=partida_actual.idpartidabingo,
    ).order_by("idpartidabingo").first()

    if siguiente:
        return siguiente

    nombre_base = str(partida_actual.nombreronda or "Ronda").strip()
    match = re.search(r"(\d+)$", nombre_base)
    if match:
        siguiente_num = int(match.group(1)) + 1
        nombre_siguiente = re.sub(r"\d+$", str(siguiente_num), nombre_base)
    else:
        total_rondas = PartidaBingo.objects.filter(
            idbingo=partida_actual.idbingo).count()
        nombre_siguiente = f"Ronda {total_rondas + 1}"

    return PartidaBingo.objects.create(
        idbingo=partida_actual.idbingo,
        nombreronda=nombre_siguiente,
        valorefectivo=partida_actual.valorefectivo or 0,
        premiomaterial=partida_actual.premiomaterial or "Ninguno",
        modalidad_victoria=partida_actual.modalidad_victoria or "Tabla Llena",
        estadopartida="Programada",
        bolascantadas="",
        ultimabola=0,
        horainicio=timezone.now(),
    )


def _finalizar_partida_y_activar_siguiente(partida, enviar_evento=True):
    """Finaliza la ronda actual y enciende la siguiente automáticamente."""
    partida.estadopartida = "Finalizada"
    partida.horafin = timezone.now()
    partida.save(update_fields=["estadopartida", "horafin"])

    siguiente = _crear_o_reusar_siguiente_partida(partida)

    if siguiente.estadopartida != "En Juego":
        siguiente.estadopartida = "En Juego"
        siguiente.horainiciopartida = timezone.now()
        siguiente.save(update_fields=["estadopartida", "horainiciopartida"])

    if enviar_evento:
        _enviar_evento_partida(
            partida.idpartidabingo,
            {
                "evento": "estado_cambiado",
                "nuevo_estado": "Finalizada",
                "id_siguiente_partida": siguiente.idpartidabingo,
            },
        )
        _enviar_evento_partida(
            siguiente.idpartidabingo,
            {
                "evento": "estado_cambiado",
                "nuevo_estado": "En Juego",
            },
        )

    return siguiente


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
        siguiente = _finalizar_partida_y_activar_siguiente(
            partida, enviar_evento=enviar_evento)
        # Lanza la primera bola de la siguiente ronda para continuidad total.
        avanzar_partida_con_bola(
            siguiente.idpartidabingo, enviar_evento=enviar_evento)
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

        while True:
            partida.refresh_from_db()
            if partida.estadopartida != "En Juego":
                break

            nueva = avanzar_partida_con_bola(
                partida.idpartidabingo, enviar_evento=True)
            if nueva is None:
                siguiente = PartidaBingo.objects.filter(
                    idbingo=partida.idbingo,
                    idpartidabingo__gt=partida.idpartidabingo,
                    estadopartida="En Juego",
                ).order_by("idpartidabingo").first()
                if not siguiente:
                    break
                partida = siguiente
                continue

            time.sleep(8)

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
