import json
import random
import uuid
from django.contrib.auth.models import User
from django.db import transaction
# NUEVO: Para borrar archivos viejos
from django.core.files.storage import default_storage
from .models import Socio, Jugador, TipoSocio, CartonPartidaBingo


def generar_matriz_bingo():
    Carton = {
        'B': sorted(random.sample(range(1, 16), 5)),
        'I': sorted(random.sample(range(16, 31), 5)),
        'N': sorted(random.sample(range(31, 46), 5)),
        'G': sorted(random.sample(range(46, 61), 5)),
        'O': sorted(random.sample(range(61, 76), 5))
    }
    Carton['N'][2] = "FREE"
    return Carton


def generar_lote_cartones(cantidad):
    nuevos_cartones = []
    firmas_existentes = set()

    while len(nuevos_cartones) < cantidad:
        matriz = generar_matriz_bingo()
        firma = tuple(
            matriz['B'] + matriz['I'] +
            [matriz['N'][0], matriz['N'][1], matriz['N'][3], matriz['N'][4]] +
            matriz['G'] + matriz['O']
        )
        if firma not in firmas_existentes:
            firmas_existentes.add(firma)
            serial_unico = f"CTN-{str(uuid.uuid4())[:8].upper()}"
            nuevos_cartones.append({
                'codigo': serial_unico,
                'matriz': matriz
            })
    return nuevos_cartones


# =========================================================
# GESTIÓN DE PERFILES, BORRADO LÓGICO Y CREDENCIALES
# =========================================================


def actualizar_socio_y_credenciales(id_socio, cedula, nombres, apellidos, telefono, estado, id_tipo_socio, password_nueva=None):
    with transaction.atomic():
        socio = Socio.objects.select_for_update().get(idsocio=id_socio)
        estado_antiguo = socio.estadosocio
        cedula_antigua = socio.cisocio

        tipo_socio_obj = TipoSocio.objects.get(idtiposocio=id_tipo_socio)
        user = None
        if estado_antiguo == 'Activo':
            user = User.objects.filter(username=cedula_antigua).first()
        else:
            user = User.objects.filter(
                username=f"inactivo_{socio.idsocio}_{cedula_antigua}"[:150]).first()

        socio.cisocio = cedula
        socio.primernombresocio = nombres
        socio.primerapellidosocio = apellidos
        socio.telefonopersonalsocio = telefono
        socio.estadosocio = estado
        socio.idtiposocio = tipo_socio_obj
        socio.save()

        if user:
            if estado == 'Inactivo':
                prefijo = f"inactivo_{socio.idsocio}_"
                if not user.username.startswith(prefijo):
                    user.username = f"{prefijo}{cedula}"[:150]
                    if user.email and not user.email.startswith(prefijo):
                        user.email = f"{prefijo}{user.email}"[:254]
                user.is_active = False
            else:
                user.username = cedula
                prefijo = f"inactivo_{socio.idsocio}_"
                if user.email and user.email.startswith(prefijo):
                    user.email = user.email.replace(prefijo, "", 1)
                user.is_active = True

            if password_nueva:
                user.set_password(password_nueva)
            user.save()


def actualizar_jugador_y_credenciales(id_jugador, alias, cedula, correo, estado, password_nueva=None):
    with transaction.atomic():
        jugador = Jugador.objects.select_for_update().get(idjugador=id_jugador)
        estado_antiguo = jugador.estadocuentajugador
        cedula_antigua = jugador.cedulaidentidadjugador

        user = None
        if cedula_antigua:
            if estado_antiguo == 'Activo':
                user = User.objects.filter(username=cedula_antigua).first()
            else:
                user = User.objects.filter(
                    username=f"inactivo_j{jugador.idjugador}_{cedula_antigua}"[:150]).first()

        jugador.aliasjugador = alias
        jugador.cedulaidentidadjugador = cedula
        jugador.correojugador = correo
        jugador.estadocuentajugador = estado
        jugador.save()

        if user:
            if estado in ['Suspendido', 'Moroso']:
                prefijo = f"inactivo_j{jugador.idjugador}_"
                if not user.username.startswith(prefijo):
                    user.username = f"{prefijo}{cedula}"[:150]
                    if user.email and not user.email.startswith(prefijo):
                        user.email = f"{prefijo}{correo}"[:254]
                user.is_active = False
            else:
                user.username = cedula
                if correo:
                    user.email = correo
                prefijo = f"inactivo_j{jugador.idjugador}_"
                if user.email and user.email.startswith(prefijo):
                    user.email = user.email.replace(prefijo, "", 1)
                user.is_active = True

            if password_nueva:
                user.set_password(password_nueva)
            user.save()


# NUEVA FUNCIÓN: Protege tu servidor borrando fotos viejas
def actualizar_avatar_perfil(request, socio, jugador, nueva_foto):
    avatar_url = None

    if jugador:
        if jugador.avatarjugador and default_storage.exists(jugador.avatarjugador.name):
            default_storage.delete(jugador.avatarjugador.name)
        jugador.avatarjugador = nueva_foto
        jugador.save()
        avatar_url = jugador.avatarjugador.url

    if socio:
        if socio.fotosocio and default_storage.exists(socio.fotosocio.name):
            default_storage.delete(socio.fotosocio.name)
        socio.fotosocio = nueva_foto
        socio.save()
        if not jugador:
            avatar_url = socio.fotosocio.url

    if avatar_url:
        request.session['avatar_url'] = avatar_url
    return True


def evaluar_patron_victoria(marcadas, modalidad):
    """Evalúa si un conjunto de índices marcados cumple un patrón de bingo."""
    marcadas = set(marcadas)
    patrones = {
        'Tabla Llena': [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]],
        'Las Cuatro Esquinas': [[0, 4, 20, 24]],
        'En Diagonal': [[0, 6, 12, 18, 24], [4, 8, 12, 16, 20]],
        'Forma de X': [[0, 4, 6, 8, 12, 16, 18, 20, 24]],
        'Forma de Cruz': [[2, 7, 10, 11, 12, 13, 14, 17, 22]],
        'Marco de Foto': [[0, 1, 2, 3, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24]],
        'Linea Vertical': [
            [0, 5, 10, 15, 20],
            [1, 6, 11, 16, 21],
            [2, 7, 12, 17, 22],
            [3, 8, 13, 18, 23],
            [4, 9, 14, 19, 24],
        ],
        'Linea Horizontal': [
            [0, 1, 2, 3, 4],
            [5, 6, 7, 8, 9],
            [10, 11, 12, 13, 14],
            [15, 16, 17, 18, 19],
            [20, 21, 22, 23, 24],
        ],
        'Forma de L': [[0, 5, 10, 15, 20, 21, 22, 23, 24]],
        'Forma de C': [[0, 1, 2, 3, 4, 5, 10, 15, 20, 21, 22, 23, 24]],
        'Forma de T': [[0, 1, 2, 3, 4, 7, 12, 17, 22]],
        'Forma de U': [[0, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24]],
        'Forma de H': [[0, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19, 20, 24]],
        'Forma de Z': [[0, 1, 2, 3, 4, 8, 12, 16, 20, 21, 22, 23, 24]],
        'Forma de Flecha': [[2, 6, 8, 12, 17, 22]],
    }
    combinaciones = patrones.get(modalidad) or patrones['Tabla Llena']
    return any(all(idx in marcadas for idx in combinacion) for combinacion in combinaciones)


def marcar_casilla_manual(id_jugador, codigo_carton, numero, id_partida):
    """Valida y acepta un marcado de casilla para un cartón asignado a la partida."""
    try:
        asignacion = CartonPartidaBingo.objects.select_related('idcarton').get(
            idjugador_id=id_jugador,
            idcarton__codigocarton=codigo_carton,
            idpartida_id=id_partida,
        )
    except CartonPartidaBingo.DoesNotExist:
        return False

    matriz = asignacion.idcarton.matriznumeros
    if isinstance(matriz, str):
        try:
            matriz = json.loads(matriz.replace("'", '"'))
        except Exception:
            return False

    numeros_carton = []
    for letra in ['B', 'I', 'N', 'G', 'O']:
        numeros_carton.extend(matriz.get(letra, []))

    numeros_texto = {str(num) for num in numeros_carton if str(num) != 'FREE'}
    return str(numero) in numeros_texto


def validar_carton_hibrido(codigo_carton, id_partida):
    """
    Árbitro Digital: Toma un código de cartón, verifica que pertenezca a la partida,
    y comprueba si sus números coinciden con las bolas cantadas.
    """
    try:
        # 1. Buscar la asignación de este cartón en la partida específica
        asignacion = CartonPartidaBingo.objects.select_related('idcarton', 'idpartida', 'idjugador').get(
            idcarton__codigocarton=codigo_carton,
            idpartida_id=id_partida
        )

        partida = asignacion.idpartida
        matriz = asignacion.idcarton.matriznumeros

        # Convertir las bolas cantadas (ej: "B1,I16,N35") a una lista limpia ['1', '16', '35']
        bolas_cantadas_str = partida.bolascantadas.replace('B', '').replace(
            'I', '').replace('N', '').replace('G', '').replace('O', '')
        bolas_cantadas_lista = [b.strip()
                                for b in bolas_cantadas_str.split(',') if b.strip()]

        # 2. Verificar los números del cartón
        numeros_carton = []
        for letra in ['B', 'I', 'N', 'G', 'O']:
            for num in matriz[letra]:
                if str(num) != 'FREE':
                    numeros_carton.append(str(num))

        # 3. La regla de oro: ¿Están TODOS los números del cartón en la lista de bolas cantadas?
        # (Aquí puedes ajustar si la regla es 'Cartón Lleno' o 'Línea', por ahora asumo Cartón Lleno)
        es_valido = all(num in bolas_cantadas_lista for num in numeros_carton)

        return {
            'existe': True,
            'valido': es_valido,
            'jugador': asignacion.idjugador.aliasjugador if asignacion.idjugador else 'Jugador Anónimo',
            'origen': 'Web' if asignacion.idjugador else 'Externo',
            'id_jugador': asignacion.idjugador.idjugador if asignacion.idjugador else None
        }

    except CartonPartidaBingo.DoesNotExist:
        # El cartón no fue comprado para esta ronda o el código es falso
        return {
            'existe': False,
            'valido': False,
            'mensaje': 'Código no registrado para esta ronda.'
        }
