import json
import os

import django
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bingo_prueba.settings")
django.setup()

from bingo.models import Bingo, CartonPartidaBingo, PartidaBingo  # noqa: E402
from bingo.services import generar_matriz_bingo  # noqa: E402
from bingo.tasks import avanzar_partida_con_bola  # noqa: E402


def matriz_valida(matriz):
    if not isinstance(matriz, dict):
        return False
    columnas = ["B", "I", "N", "G", "O"]
    if any(col not in matriz or not isinstance(matriz[col], list) or len(matriz[col]) != 5 for col in columnas):
        return False
    try:
        return (
            all(1 <= int(n) <= 15 for n in matriz["B"]) and
            all(16 <= int(n) <= 30 for n in matriz["I"]) and
            str(matriz["N"][2]).upper() == "FREE" and
            all(31 <= int(matriz["N"][i]) <= 45 for i in [0, 1, 3, 4]) and
            all(46 <= int(n) <= 60 for n in matriz["G"]) and
            all(61 <= int(n) <= 75 for n in matriz["O"])
        )
    except Exception:
        return False


def main():
    bingos = list(Bingo.objects.exclude(
        estadobingo__in=["Finalizado", "Cancelado"]))
    cartones_corregidos = 0
    bingos_reiniciados = 0
    partidas_iniciadas = []

    asignaciones = CartonPartidaBingo.objects.filter(
        idpartida__idbingo__in=bingos
    ).select_related("idcarton")

    for asignacion in asignaciones:
        matriz = asignacion.idcarton.matriznumeros
        if isinstance(matriz, str):
            try:
                matriz = json.loads(matriz.replace("'", '"'))
            except Exception:
                matriz = {}

        if not matriz_valida(matriz):
            asignacion.idcarton.matriznumeros = generar_matriz_bingo()
            asignacion.idcarton.save(update_fields=["matriznumeros"])
            cartones_corregidos += 1

    for bingo in bingos:
        partidas = list(PartidaBingo.objects.filter(
            idbingo=bingo).order_by("idpartidabingo"))
        if not partidas:
            continue

        for partida in partidas:
            partida.estadopartida = "Programada"
            partida.bolascantadas = ""
            partida.ultimabola = 0
            partida.horainiciopartida = None
            partida.horafin = None
            partida.haydesempate = False
            partida.idbingadores = ""
            partida.save(update_fields=[
                "estadopartida",
                "bolascantadas",
                "ultimabola",
                "horainiciopartida",
                "horafin",
                "haydesempate",
                "idbingadores",
            ])

        primera = partidas[0]
        primera.estadopartida = "En Juego"
        primera.horainiciopartida = timezone.now()
        primera.save(update_fields=["estadopartida", "horainiciopartida"])

        if bingo.estadobingo != "En Curso":
            bingo.estadobingo = "En Curso"
            bingo.save(update_fields=["estadobingo"])

        avanzar_partida_con_bola(primera.idpartidabingo, enviar_evento=False)

        bingos_reiniciados += 1
        partidas_iniciadas.append(str(primera.idpartidabingo))

    print(
        "RESET_OK "
        f"bingos_reiniciados={bingos_reiniciados} "
        f"cartones_corregidos={cartones_corregidos} "
        f"partidas_iniciadas={','.join(partidas_iniciadas)}"
    )


if __name__ == "__main__":
    main()
