import importlib
import json
import random
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q, Sum
from django.http import HttpResponse
from channels.layers import get_channel_layer
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.utils import timezone

from .models import (
    Ahorro,
    AporteSemanal,
    Bingo,
    Carton,
    CartonPartidaBingo,
    ConfiguracionWeb,
    CuentaBancaria,
    Jugador,
    MensajeChat,
    MetodoPago,
    Pago,
    PartidaBingo,
    PlataformaJuego,
    Prestamo,
    Regalo,
    SesionJuego,
    Socio,
    TipoSocio,
    UnidadMonetaria,
)
from .services import (
    actualizar_jugador_y_credenciales,
    actualizar_socio_y_credenciales,
    generar_lote_cartones,
    validar_carton_hibrido,
)
from .tasks import avanzar_partida_con_bola, fabricar_cartones_maestros_task

try:
    openpyxl = importlib.import_module('openpyxl')
    styles_module = importlib.import_module('openpyxl.styles')
    Alignment = styles_module.Alignment
    Font = styles_module.Font
    PatternFill = styles_module.PatternFill
except ImportError:  # pragma: no cover - fallback para entornos sin OpenPyXL
    openpyxl = None
    Alignment = Font = PatternFill = None

try:
    pisa = importlib.import_module('xhtml2pdf.pisa')
except ImportError:  # pragma: no cover - fallback para entornos sin xhtml2pdf
    pisa = None

# Create your views here.


def obtener_socio_usuario(user):
    if not user:
        return None

    socio = Socio.objects.filter(cisocio=user.username).first()
    if socio:
        return socio

    jugador_por_user = Jugador.objects.filter(
        Q(cedulaidentidadjugador=user.username)
        | Q(aliasjugador=user.username)
        | Q(correojugador__iexact=(user.email or ''))
    ).select_related('idsocio').order_by('-idjugador').first()

    if jugador_por_user and jugador_por_user.idsocio:
        return jugador_por_user.idsocio

    if jugador_por_user and not jugador_por_user.idsocio and jugador_por_user.cedulaidentidadjugador:
        socio_por_cedula = Socio.objects.filter(
            cisocio=jugador_por_user.cedulaidentidadjugador
        ).first()
        if socio_por_cedula:
            jugador_por_user.idsocio = socio_por_cedula
            try:
                jugador_por_user.save(update_fields=['idsocio'])
            except Exception:
                pass
            return socio_por_cedula

    return None


def obtener_jugador_usuario(user):
    if not user:
        return None

    socio = obtener_socio_usuario(user)

    filtros = Q(cedulaidentidadjugador=user.username) | Q(
        aliasjugador=user.username)
    if getattr(user, 'email', None):
        filtros |= Q(correojugador__iexact=user.email)
    if socio:
        filtros |= Q(idsocio=socio)

    jugador = Jugador.objects.filter(filtros).order_by('-idjugador').first()

    # Normaliza vínculo socio<->jugador para evitar bugs de resolución posteriores.
    if jugador and socio:
        update_fields = []
        if not jugador.idsocio:
            jugador.idsocio = socio
            update_fields.append('idsocio')
        if not jugador.cedulaidentidadjugador:
            cedula_en_uso = Jugador.objects.filter(
                cedulaidentidadjugador=socio.cisocio
            ).exclude(idjugador=jugador.idjugador).exists()
            if not cedula_en_uso:
                jugador.cedulaidentidadjugador = socio.cisocio
                update_fields.append('cedulaidentidadjugador')
        if update_fields:
            try:
                jugador.save(update_fields=update_fields)
            except IntegrityError:
                # Si hay datos heredados inconsistentes, evitar romper el flujo del socio.
                pass

    return jugador


def consolidar_jugadores_duplicados(idsocio, jugador_preferido=None):
    if not idsocio:
        return jugador_preferido

    jugadores = list(
        Jugador.objects.filter(idsocio=idsocio).order_by('-idjugador')
    )
    if len(jugadores) <= 1:
        return jugadores[0] if jugadores else jugador_preferido

    principal = None
    if jugador_preferido and jugador_preferido.idsocio_id == idsocio.idsocio:
        principal = jugador_preferido
    if principal is None:
        principal = jugadores[0]

    duplicados = [j for j in jugadores if j.idjugador != principal.idjugador]
    if not duplicados:
        return principal

    with transaction.atomic():
        # Consolidar saldo evita que dinero aprobado en préstamos quede fragmentado.
        saldo_extra = sum((j.saldocreditojugador or Decimal('0.00'))
                          for j in duplicados)
        if saldo_extra:
            principal.saldocreditojugador = (
                principal.saldocreditojugador or Decimal('0.00')) + saldo_extra
            principal.save(update_fields=['saldocreditojugador'])

        ids_duplicados = [j.idjugador for j in duplicados]
        CartonPartidaBingo.objects.filter(
            idjugador_id__in=ids_duplicados).update(idjugador=principal)
        SesionJuego.objects.filter(
            idjugador_id__in=ids_duplicados).update(idjugador=principal)
        PartidaBingo.objects.filter(idjugadororganador_id__in=ids_duplicados).update(
            idjugadororganador=principal)
        Jugador.objects.filter(idjugador__in=ids_duplicados).delete()

    return principal


def obtener_jugador_request(request):
    jugador = obtener_jugador_usuario(request.user)
    socio = obtener_socio_usuario(request.user)

    if socio:
        jugador = consolidar_jugadores_duplicados(
            socio, jugador_preferido=jugador)

    if not jugador and request.session.get('jugador_id'):
        jugador = Jugador.objects.filter(
            idjugador=request.session.get('jugador_id')
        ).first()

    if not jugador and request.session.get('socio_id'):
        jugador = Jugador.objects.filter(
            idsocio_id=request.session.get('socio_id')
        ).order_by('-idjugador').first()

    if not jugador:
        if not socio and request.session.get('socio_id'):
            socio = Socio.objects.filter(
                idsocio=request.session.get('socio_id')).first()
        if socio:
            jugador = consolidar_jugadores_duplicados(socio)

    if jugador and jugador.idsocio_id:
        jugador = consolidar_jugadores_duplicados(
            jugador.idsocio, jugador_preferido=jugador)

    if jugador:
        request.session['jugador_id'] = jugador.idjugador
        if jugador.idsocio_id:
            request.session['socio_id'] = jugador.idsocio_id

    return jugador


# ==========================================
# 1. COMUNES (Páginas públicas y base)
# ==========================================
def inicio(request):
    preguntar_jugador = request.session.pop('preguntar_jugador', False)
    es_jugador = False
    mostrar_promo_socio = False
    saldo_jugador = None

    if request.user.is_authenticated and not request.user.is_staff:
        jugador = obtener_jugador_usuario(request.user)
        if jugador:
            es_jugador = True
            saldo_jugador = jugador.saldocreditojugador
            if not jugador.idsocio and not request.session.get('promo_socio_visto', False):
                mostrar_promo_socio = True
                request.session['promo_socio_visto'] = True

    config_web = ConfiguracionWeb.objects.first()

    bingos_activos = Bingo.objects.filter(
        estadobingo__in=['Programado', 'En Curso']
    ).select_related('idunidadmonetaria').order_by('fechaprogramadabingo')

    ahora = timezone.now()

    for b in bingos_activos:
        if b.fechaprogramadabingo:
            hora_apertura = b.fechaprogramadabingo - timedelta(minutes=30)
            partida_activa = PartidaBingo.objects.filter(
                idbingo=b,
                estadopartida__in=['Programada', 'En Juego']
            ).order_by('idpartidabingo').first()

            if ahora >= hora_apertura and partida_activa:
                b.sala_abierta = True
                b.id_partida_a_entrar = partida_activa.idpartidabingo
            else:
                b.sala_abierta = False
        else:
            b.sala_abierta = False

    ultimas_asignaciones_regalo = AporteSemanal.objects.filter(idregalo__isnull=False).select_related(
        'idsocio', 'idregalo').order_by('-idaporte')[:200]

    ganador_por_regalo = {}
    for asignacion in ultimas_asignaciones_regalo:
        rid = asignacion.idregalo_id
        if rid not in ganador_por_regalo:
            ganador_por_regalo[rid] = asignacion

    regalos_lista = list(Regalo.objects.all().order_by('-idregalo'))
    for regalo in regalos_lista:
        regalo.asignacion_actual = ganador_por_regalo.get(regalo.idregalo)

    contexto = {
        'preguntar_jugador': preguntar_jugador,
        'es_jugador': es_jugador,
        'config_web': config_web,
        'bingos_activos': bingos_activos,
        'mostrar_promo_socio': mostrar_promo_socio,
        'saldo_jugador': saldo_jugador,
    }
    return render(request, 'comunes/inicio.html', contexto)


def como_jugar(request):
    """Página de instrucciones sobre cómo jugar bingo"""
    contexto = {}
    return render(request, 'comunes/como_jugar.html', contexto)


def inicio_sesion(request):
    if request.user.is_authenticated:
        return redirect('dashboard' if request.user.is_staff else 'inicio')

    if request.method == 'POST':
        identificador = request.POST.get('identificador')
        password = request.POST.get('password')

        user = User.objects.filter(
            Q(username=identificador) | Q(email=identificador)).first()

        if user and user.check_password(password):
            if not user.is_active:
                messages.error(
                    request, 'Esta cuenta ha sido desactivada o suspendida del sistema.')
                return redirect('login')

            usuario_autenticado = authenticate(
                request,
                username=user.username,
                password=password,
            )
            if not usuario_autenticado:
                messages.error(
                    request,
                    'No fue posible iniciar sesión con este usuario. Intenta nuevamente.',
                )
                return redirect('login')

            login(request, usuario_autenticado)

            socio = Socio.objects.filter(cisocio=user.username).first()
            jugador = obtener_jugador_usuario(user)

            nombre_mostrar = user.first_name or user.username
            avatar_url = None

            if jugador:
                nombre_mostrar = jugador.aliasjugador or user.first_name or user.username
                if jugador.avatarjugador:
                    avatar_url = jugador.avatarjugador.url

            foto_socio = getattr(socio, 'fotosocio', None) if socio else None
            if foto_socio and not avatar_url:
                avatar_url = foto_socio.url

            request.session['user_nombre'] = nombre_mostrar
            request.session['avatar_url'] = avatar_url
            request.session['socio_id'] = socio.idsocio if socio else None
            request.session['jugador_id'] = jugador.idjugador if jugador else None

            messages.success(
                request, f'¡Bienvenido de vuelta, {nombre_mostrar}!')
            return redirect('dashboard' if user.is_staff else 'inicio')

        messages.error(
            request, 'Credenciales incorrectas. Verifica tu usuario/cédula/correo y contraseña.')

    return render(request, 'cuenta/inicio_secion.html')


def cerrar_sesion(request):
    logout(request)
    return redirect('inicio')
# Registro de usuarios


def seleccion_registro(request): return render(
    request, 'cuenta/seleccion_registro.html')


def registro_socio(request):
    if request.method == 'POST':
        primer_nombre = request.POST.get('primer_nombre')
        segundo_nombre = request.POST.get('segundo_nombre')
        primer_apellido = request.POST.get('primer_apellido')
        segundo_apellido = request.POST.get('segundo_apellido')
        cedula = request.POST.get('cedula')
        fecha_nacimiento_str = request.POST.get('fecha_nacimiento')
        telefono_personal = request.POST.get('telefono_personal')
        direccion = request.POST.get('direccion')
        sexo = request.POST.get('sexo')
        email = request.POST.get('email')
        password = request.POST.get('password')

        if not cedula or not cedula.isdigit() or len(cedula) != 10:
            messages.error(
                request, "Error de seguridad: La cédula debe tener exactamente 10 dígitos numéricos.")
            return redirect('registro_socio')

        if not telefono_personal or not telefono_personal.isdigit() or len(telefono_personal) != 10:
            messages.error(
                request, "Error de seguridad: El teléfono debe tener exactamente 10 dígitos numéricos.")
            return redirect('registro_socio')

        if User.objects.filter(username=cedula).exists():
            messages.error(request, "Esta cédula ya está registrada.")
            return redirect('registro_socio')

        try:
            fecha_nac = datetime.strptime(
                fecha_nacimiento_str, '%Y-%m-%d').date()
            if fecha_nac > date.today():
                messages.error(
                    request, "La fecha de nacimiento no puede ser en el futuro.")
                return redirect('registro_socio')
        except ValueError:
            messages.error(request, "Formato de fecha inválido.")
            return redirect('registro_socio')

        try:
            user = User.objects.create_user(
                username=cedula, email=email, password=password,
                first_name=primer_nombre, last_name=primer_apellido,
            )
            tipo_base = TipoSocio.objects.first()
            if not tipo_base:
                user.delete()
                messages.error(
                    request, "Error crítico: No hay 'Tipos de Socio' configurados.")
                return redirect('registro_socio')

            socio_nuevo = Socio.objects.create(
                idtiposocio=tipo_base,
                primernombresocio=primer_nombre,
                segundonombresocio=segundo_nombre,
                primerapellidosocio=primer_apellido,
                segundoapellidosocio=segundo_apellido,
                cisocio=cedula,
                fechanacimientosocio=fecha_nac,
                telefonopersonalsocio=telefono_personal,
                direcciondomiciliosocio=direccion,
                sexosocio=sexo,
                estadosocio='Activo',
            )
            login(request, user)
            request.session['preguntar_jugador'] = True
            request.session['user_nombre'] = primer_nombre
            request.session['socio_id'] = socio_nuevo.idsocio
            request.session['jugador_id'] = None
            return redirect('inicio')
        except Exception as e:
            if 'user' in locals() and user.id:
                user.delete()
            messages.error(request, f"Error en el formulario: {str(e)}")
            return redirect('registro_socio')

    return render(request, 'cuenta/registro_socio.html')


def registro_jugador(request):
    if request.method == 'POST':
        alias = (request.POST.get('aliasjugador') or '').strip()

        if not alias:
            messages.error(request, "Debes ingresar un alias para jugar.")
            return redirect('registro_jugador')

        alias_en_uso = Jugador.objects.filter(aliasjugador__iexact=alias)

        if request.user.is_authenticated:
            try:
                socio_vinculado = obtener_socio_usuario(request.user)
                if not socio_vinculado:
                    messages.error(
                        request, "No se encontró un perfil de socio asociado a tu cuenta.")
                    return redirect('perfil')
                correo_actual = (request.user.email or '').strip()

                jugador_existente = Jugador.objects.filter(
                    Q(cedulaidentidadjugador=socio_vinculado.cisocio)
                    | Q(idsocio=socio_vinculado)
                ).first()

                if not jugador_existente and correo_actual:
                    jugador_por_correo = Jugador.objects.filter(
                        correojugador__iexact=correo_actual
                    ).first()
                    if jugador_por_correo and (
                        jugador_por_correo.idsocio_id == socio_vinculado.idsocio
                        or jugador_por_correo.cedulaidentidadjugador == socio_vinculado.cisocio
                    ):
                        jugador_existente = jugador_por_correo

                if jugador_existente:
                    if alias_en_uso.exclude(idjugador=jugador_existente.idjugador).exists():
                        messages.error(
                            request, "Ese alias ya está en uso. Elige otro diferente.")
                        return redirect('registro_jugador')

                    jugador_existente.aliasjugador = alias
                    update_fields = ['aliasjugador']

                    if not jugador_existente.idsocio:
                        jugador_existente.idsocio = socio_vinculado
                        update_fields.append('idsocio')

                    if not jugador_existente.cedulaidentidadjugador:
                        cedula_en_uso = Jugador.objects.filter(
                            cedulaidentidadjugador=socio_vinculado.cisocio
                        ).exclude(idjugador=jugador_existente.idjugador).exists()
                        if not cedula_en_uso:
                            jugador_existente.cedulaidentidadjugador = socio_vinculado.cisocio
                            update_fields.append('cedulaidentidadjugador')

                    if correo_actual and not jugador_existente.correojugador:
                        jugador_existente.correojugador = correo_actual
                        update_fields.append('correojugador')

                    jugador_existente.save(update_fields=update_fields)
                    request.session['user_nombre'] = alias
                    request.session['jugador_id'] = jugador_existente.idjugador
                    request.session['socio_id'] = socio_vinculado.idsocio
                    messages.success(
                        request, f"Alias actualizado correctamente a '{alias}'.")
                    return redirect('inicio')

                if alias_en_uso.exists():
                    messages.error(
                        request, "Ese alias ya está en uso. Elige otro diferente.")
                    return redirect('registro_jugador')

                correo_para_jugador = correo_actual or None
                if correo_actual and Jugador.objects.filter(correojugador__iexact=correo_actual).exists():
                    correo_para_jugador = None
                    messages.warning(
                        request,
                        "Tu correo ya existe en otro perfil de jugador. Se activó tu alias sin correo para evitar bloqueo.",
                    )

                jugador_creado = Jugador.objects.create(
                    idsocio=socio_vinculado,
                    aliasjugador=alias,
                    nombresjugador=socio_vinculado.primernombresocio,
                    cedulaidentidadjugador=socio_vinculado.cisocio,
                    correojugador=correo_para_jugador,
                )
                request.session['user_nombre'] = alias
                request.session['jugador_id'] = jugador_creado.idjugador
                request.session['socio_id'] = socio_vinculado.idsocio
                messages.success(
                    request, f"¡Perfil de juego activado como '{alias}'!")
                return redirect('inicio')
            except Exception:
                messages.error(
                    request, "Error al vincular el perfil de juego.")
        else:
            nombres = request.POST.get('nombresjugador')
            apellidos = request.POST.get('apellidosjugador')
            cedula = request.POST.get('cedula')
            correo = request.POST.get('correojugador')
            password = request.POST.get('password')

            if cedula and (not cedula.isdigit() or len(cedula) != 10):
                messages.error(
                    request, "Error de seguridad: La cédula debe tener exactamente 10 dígitos numéricos.")
                return redirect('registro_jugador')

            if User.objects.filter(username=cedula).exists():
                messages.error(request, "Cédula ya registrada.")
                return redirect('registro_jugador')

            if alias_en_uso.exists():
                messages.error(
                    request, "Ese alias ya está en uso. Elige otro diferente.")
                return redirect('registro_jugador')

            # Validar correo duplicado antes de crear
            if correo and Jugador.objects.filter(correojugador__iexact=correo).exists():
                messages.error(
                    request, "El correo ya está registrado en otro perfil de jugador.")
                return redirect('registro_jugador')

            try:
                user = User.objects.create_user(
                    username=cedula, email=correo, password=password,
                    first_name=nombres, last_name=apellidos,
                )
                jugador_creado = Jugador.objects.create(
                    aliasjugador=alias, nombresjugador=nombres,
                    apellidosjugador=apellidos, cedulaidentidadjugador=cedula,
                    correojugador=correo,
                )
                login(request, user)
                request.session['user_nombre'] = alias
                request.session['jugador_id'] = jugador_creado.idjugador
                request.session['socio_id'] = None
                messages.success(
                    request, f"¡Bienvenido a la sala de juegos, {alias}!")
                return redirect('inicio')
            except Exception as e:
                if 'user' in locals() and user.id:
                    user.delete()
                messages.error(request, f"Error: {str(e)}")
                return redirect('registro_jugador')

    return render(request, 'cuenta/registro_jugador.html')
# ---- Helper: actualiza el avatar del jugador y la sesión ----


def actualizar_avatar_perfil(request, socio, jugador, nueva_foto):
    if jugador:
        if jugador.avatarjugador:
            jugador.avatarjugador.delete(save=False)
        jugador.avatarjugador = nueva_foto
        jugador.save()
        request.session['avatar_url'] = jugador.avatarjugador.url


# Gestión del perfil del usuario logueado
@login_required
def perfil(request):
    user = request.user
    socio = obtener_socio_usuario(user)
    if not socio and request.session.get('socio_id'):
        socio = Socio.objects.filter(
            idsocio=request.session.get('socio_id')).first()
    jugador = obtener_jugador_usuario(user)
    if not jugador and request.session.get('jugador_id'):
        jugador = Jugador.objects.filter(
            idjugador=request.session.get('jugador_id')).first()

    if socio:
        request.session['socio_id'] = socio.idsocio
    if jugador:
        request.session['jugador_id'] = jugador.idjugador

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'actualizar_datos':
                nuevo_correo = request.POST.get('correo')
                if nuevo_correo:
                    user.email = nuevo_correo
                    user.save()
                if socio:
                    socio.telefonopersonalsocio = request.POST.get(
                        'telefono', socio.telefonopersonalsocio)
                    socio.save()
                if jugador:
                    jugador.aliasjugador = request.POST.get(
                        'alias', jugador.aliasjugador)
                    jugador.correojugador = nuevo_correo
                    jugador.save()
                    request.session['user_nombre'] = jugador.aliasjugador
                messages.success(
                    request, "Tus datos de contacto han sido actualizados.")

            elif action == 'actualizar_avatar':
                nueva_foto = request.FILES.get('avatar')
                if nueva_foto:
                    actualizar_avatar_perfil(
                        request, socio, jugador, nueva_foto)
                    messages.success(
                        request, "¡Tu foto de perfil luce genial!")

            elif action == 'actualizar_password':
                actual = request.POST.get('password_actual')
                nueva = request.POST.get('password_nueva')
                if user.check_password(actual):
                    user.set_password(nueva)
                    user.save()
                    update_session_auth_hash(request, user)
                    messages.success(
                        request, "Tu contraseña ha sido cambiada de forma segura.")
                else:
                    messages.error(
                        request, "La contraseña actual no coincide. No se guardaron los cambios.")

            elif action == 'ascender_socio':
                cedula = request.POST.get('cedula')
                primer_nombre = request.POST.get('primer_nombre')
                segundo_nombre = request.POST.get('segundo_nombre', '')
                primer_apellido = request.POST.get('primer_apellido')
                segundo_apellido = request.POST.get('segundo_apellido')
                telefono = request.POST.get('telefono')
                direccion = request.POST.get('direccion')
                fecha_nacimiento_str = request.POST.get('fecha_nacimiento')
                sexo = request.POST.get('sexo')
                try:
                    fecha_nac = datetime.strptime(
                        fecha_nacimiento_str, '%Y-%m-%d').date()
                    tipo_base = TipoSocio.objects.first()
                    nuevo_socio = Socio.objects.create(
                        idtiposocio=tipo_base,
                        primernombresocio=primer_nombre,
                        segundonombresocio=segundo_nombre,
                        primerapellidosocio=primer_apellido,
                        segundoapellidosocio=segundo_apellido,
                        cisocio=cedula,
                        fechanacimientosocio=fecha_nac,
                        telefonopersonalsocio=telefono,
                        direcciondomiciliosocio=direccion,
                        sexosocio=sexo,
                        estadosocio='Activo'
                    )
                    user.username = cedula
                    user.first_name = primer_nombre
                    user.last_name = primer_apellido
                    user.save()
                    if jugador:
                        jugador.idsocio = nuevo_socio
                        jugador.nombresjugador = None
                        jugador.apellidosjugador = None
                        jugador.save()
                    messages.success(
                        request, "¡Felicidades! Ahora eres Socio oficial. Tus datos legales han sido registrados con éxito.")
                except Exception as e:
                    messages.error(
                        request, f"Error al procesar la solicitud de socio: {str(e)}")
        except Exception as e:
            messages.error(request, f"Error al actualizar el perfil: {str(e)}")
        return redirect('perfil')

    historial_compras = []
    historial_prestamos = []
    historial_ahorros = []
    if jugador:
        historial_compras = CartonPartidaBingo.objects.filter(idjugador=jugador).select_related(
            'idpartida', 'idcarton').order_by('-fechacompra')[:15]
    if socio:
        historial_prestamos = Prestamo.objects.filter(
            idsocio=socio).order_by('-fechasolicitud')
        historial_ahorros = Ahorro.objects.filter(
            idsocio=socio).order_by('-fechaahorro')[:15]

    contexto = {
        'socio': socio,
        'jugador': jugador,
        'historial_compras': historial_compras,
        'historial_prestamos': historial_prestamos,
        'historial_ahorros': historial_ahorros,
    }
    return render(request, 'cuenta/perfil.html', contexto)


@login_required
def mis_cartones(request): pass  # reemplazado abajo


def descargar_cartones_pdf(request): return redirect('mis_cartones')


# ==========================================
# 3. ADMINISTRADOR (Consolas de Mando)
# ==========================================
# La lógica completa del dashboard se gestiona más abajo para evitar
# definiciones duplicadas y mantener el flujo consistente.

# ==========================================
# 4. NEGOCIO (Finanzas y Ventas)
# ==========================================

def finanzas(request):
    return render(request, 'negocio/control_aportes.html')


@login_required
def creditos(request):
    jugador = obtener_jugador_request(request)
    socio = obtener_socio_usuario(request.user)

    if not socio and request.session.get('socio_id'):
        socio = Socio.objects.filter(
            idsocio=request.session.get('socio_id')).first()

    if not jugador and request.session.get('jugador_id'):
        jugador = Jugador.objects.filter(
            idjugador=request.session.get('jugador_id')).first()

    if not jugador and socio:
        jugador = Jugador.objects.filter(
            idsocio=socio).order_by('-idjugador').first()

    if socio:
        request.session['socio_id'] = socio.idsocio
    if jugador:
        request.session['jugador_id'] = jugador.idjugador

    if not socio:
        messages.warning(
            request,
            "Necesitas estar registrado como socio para solicitar préstamos.",
        )
        return redirect('perfil')

    if request.method == 'POST':
        try:
            monto_solicitado = Decimal(request.POST.get('monto', '0') or '0')
            cuotas = int(request.POST.get('cuotas', '1') or '1')
            tasa = Decimal(request.POST.get('tasa', '12.00') or '12.00')

            if monto_solicitado <= 0:
                raise ValueError('El monto debe ser mayor a 0.')
            if cuotas < 1:
                raise ValueError(
                    'El número de cuotas debe ser mayor o igual a 1.')
            if tasa < 0:
                raise ValueError('La tasa no puede ser negativa.')

            interes = (monto_solicitado * tasa) / Decimal('100')
            total_pagar = monto_solicitado + interes

            Prestamo.objects.create(
                idsocio=socio,
                montoprestamosolicitado=monto_solicitado,
                tasainteres=tasa,
                montototalpagar=total_pagar,
                saldopendiente=total_pagar,
                numerocuotas=cuotas,
                fechasolicitud=timezone.now().date(),
                fechavencimiento=timezone.now().date() + timedelta(days=30 * cuotas),
                estadoprestamo='Solicitado',
            )

            messages.success(
                request,
                "Tu solicitud de préstamo fue registrada correctamente y está en revisión.",
            )
            return redirect('creditos')
        except Exception as e:
            messages.error(
                request, f"No se pudo registrar la solicitud: {str(e)}")

    historial_prestamos = Prestamo.objects.filter(
        idsocio=socio).order_by('-fechasolicitud')
    saldo_total_pendiente = historial_prestamos.exclude(
        estadoprestamo='Liquidado'
    ).aggregate(total=Sum('saldopendiente'))['total'] or Decimal('0.00')

    contexto = {
        'jugador': jugador,
        'socio': socio,
        'historial_prestamos': historial_prestamos,
        'saldo_total_pendiente': saldo_total_pendiente,
        'saldo_credito_jugador': jugador.saldocreditojugador if jugador else Decimal('0.00'),
    }
    return render(request, 'negocio/creditos.html', contexto)


@login_required
def regalos(request):
    jugador = obtener_jugador_usuario(request.user)
    socio = obtener_socio_usuario(request.user)

    if not socio and request.session.get('socio_id'):
        socio = Socio.objects.filter(
            idsocio=request.session.get('socio_id')).first()

    if not jugador and request.session.get('jugador_id'):
        jugador = Jugador.objects.filter(
            idjugador=request.session.get('jugador_id')).first()

    if not jugador and socio:
        jugador = Jugador.objects.filter(
            idsocio=socio).order_by('-idjugador').first()

    if socio:
        request.session['socio_id'] = socio.idsocio
    if jugador:
        request.session['jugador_id'] = jugador.idjugador

    if not socio:
        messages.warning(
            request,
            "Necesitas un perfil de socio para acceder al sistema de regalos.",
        )
        return redirect('perfil')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'reclamar_regalo':
            id_regalo = request.POST.get('id_regalo')
            try:
                with transaction.atomic():
                    regalo = Regalo.objects.select_for_update().get(
                        idregalo=id_regalo)

                    if regalo.estadoregalo != 'Acumulado':
                        messages.warning(
                            request,
                            "Este regalo ya no está disponible para canje.",
                        )
                    else:
                        referencia = f"CANJE_WEB_{request.user.username}_{uuid.uuid4().hex[:6].upper()}"
                        AporteSemanal.objects.create(
                            idsocio=socio,
                            idregalo=regalo,
                            idpartida=None,
                            numerosemana=timezone.now().isocalendar().week,
                            fechaplanificadadada=timezone.now(),
                            metodoingreso='Fisico',
                            referenciaingreso=referencia,
                            estadoaporte='Al Dia',
                        )

                        regalo.estadoregalo = 'Sorteado'
                        regalo.save(update_fields=['estadoregalo'])

                        messages.success(
                            request,
                            f"Canje exitoso. Reservaste el regalo '{regalo.nombreregalo}'.",
                        )
            except Regalo.DoesNotExist:
                messages.error(request, "El regalo seleccionado no existe.")
            except Exception as e:
                messages.error(
                    request, f"No se pudo procesar el canje: {str(e)}")

            return redirect('regalos')

    regalos_disponibles = Regalo.objects.filter(
        estadoregalo='Acumulado').order_by('-fechaultimaactualizacion')

    historial_canje = AporteSemanal.objects.filter(
        idsocio=socio,
        idregalo__isnull=False,
    ).select_related('idregalo').order_by('-fechaplanificadadada')[:40]

    contexto = {
        'jugador': jugador,
        'socio': socio,
        'regalos_disponibles': regalos_disponibles,
        'historial_canje': historial_canje,
        'total_regalos_historial': historial_canje.count(),
    }
    return render(request, 'cuenta/regalo.html', contexto)


@login_required
def partidas(request):
    """Vista para mostrar todas las partidas activas disponibles para jugar"""
    jugador = obtener_jugador_usuario(request.user)
    if not jugador:
        return redirect('registro_jugador')

    # Mostrar más salas de espera: incluir TODAS las Programadas,
    # y también las En Juego que sigan activas.
    partidas_filtradas = list(
        PartidaBingo.objects.filter(
            estadopartida__in=['Programada', 'En Juego'],
            idbingo__estadobingo__in=['Programado', 'En Curso'],
        )
        .select_related('idbingo', 'idbingo__idunidadmonetaria')
        .order_by('estadopartida', 'idbingo__fechaprogramadabingo', 'idpartidabingo')
    )

    # Asignar datos adicionales a cada partida
    for partida in partidas_filtradas:
        # Contar cuántos cartones tengo para esta partida
        cartones_count = CartonPartidaBingo.objects.filter(
            idjugador=jugador,
            idpartida=partida
        ).count()
        partida.mis_cartones = cartones_count

        # Contar jugadores activos en esta partida
        count = Jugador.objects.filter(
            sesionjuego__idpartida=partida,
            sesionjuego__estadosesion='Activa'
        ).distinct().count()
        partida.jugadores_activos = count

    contexto = {
        'partidas_en_juego': partidas_filtradas,
    }
    return render(request, 'partida/partidas_activas.html', contexto)


def sala_espera(request, id_partida):
    if not request.user.is_authenticated:
        return render(request, 'cuenta/accceso_denegado.html')

    jugador = obtener_jugador_usuario(request.user)
    if not jugador:
        return redirect('registro_jugador')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)

    if partida.estadopartida == 'Finalizada':
        messages.info(request, "Esta sala ya finalizó y fue retirada.")
        return redirect('partidas')

    inicio_programado = partida.idbingo.fechaprogramadabingo

    if partida.estadopartida == 'Programada' and inicio_programado and timezone.now() >= inicio_programado:
        try:
            channel_layer = get_channel_layer()
            partida.estadopartida = 'En Juego'
            if not partida.horainiciopartida:
                partida.horainiciopartida = timezone.now()
            partida.save()

            bingo_padre = partida.idbingo
            if bingo_padre and bingo_padre.estadobingo == 'Programado':
                bingo_padre.estadobingo = 'En Curso'
                bingo_padre.save()

            async_to_sync(channel_layer.group_send)(
                f'bingo_partida_{partida.idpartidabingo}',
                {'type': 'evento_partida', 'datos': {
                    'evento': 'estado_cambiado', 'nuevo_estado': 'En Juego'}}
            )
            return redirect('tablero_tiempo_real', id_partida=partida.idpartidabingo)
        except Exception:
            # Si algo falla, continuar mostrando la sala de espera para no bloquear al usuario
            pass

    if partida.estadopartida == 'En Juego':
        return redirect('tablero_tiempo_real', id_partida=partida.idpartidabingo)

    if partida.estadopartida in ['Verificando', 'Desempate'] and partida.idbingadores:
        ids_vip = [int(i.strip())
                   for i in str(partida.idbingadores).split(',') if i.strip()]
        if jugador.idjugador in ids_vip:
            return redirect('sala_espera_desempate', id_partida=partida.idpartidabingo)

    jugadores_en_sala = Jugador.objects.filter(
        sesionjuego__idpartida=partida,
        sesionjuego__estadosesion='Activa'
    ).distinct().order_by('aliasjugador')

    mensajes_historial = MensajeChat.objects.filter(
        idbingo=partida.idbingo).order_by('fechahora')

    contexto = {
        'partida': partida,
        'jugador': jugador,
        'jugadores_en_sala': jugadores_en_sala,
        'mensajes_historial': mensajes_historial,
        'inicio_programado_iso': inicio_programado.isoformat() if inicio_programado else '',
    }
    return render(request, 'partida/sala_espera.html', contexto)


@login_required
def sala_espera_desempate(request, id_partida):
    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)

    if partida.estadopartida == 'Finalizada':
        return redirect('inicio')

    jugadores_en_sala = Jugador.objects.filter(
        sesionjuego__idpartida=partida,
        sesionjuego__estadosesion='Activa',
    ).distinct().order_by('aliasjugador')

    jugador = obtener_jugador_usuario(request.user)
    mensajes_historial = MensajeChat.objects.filter(
        idbingo=partida.idbingo).order_by('fechahora')

    contexto = {
        'partida': partida,
        'jugador': jugador,
        'jugadores_en_sala': jugadores_en_sala,
        'mensajes_historial': mensajes_historial,
    }
    return render(request, 'partida/sala_espera_desempate.html', contexto)


@login_required
def tablero_tiempo_real(request, id_partida):
    jugador = obtener_jugador_request(request)
    if not jugador:
        messages.warning(
            request, "Necesitas un perfil de jugador para entrar a la sala.")
        return redirect('inicio')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)

    if partida.estadopartida == 'Programada':
        return redirect('sala_espera', id_partida=partida.idpartidabingo)

    if partida.estadopartida in ['Verificando', 'Desempate']:
        return redirect('sala_espera_desempate', id_partida=partida.idpartidabingo)
    elif partida.estadopartida == 'Finalizada':
        messages.info(request, "Esta ronda ha finalizado.")
        return redirect('inicio')

    cartones_asignados = CartonPartidaBingo.objects.filter(
        idjugador=jugador,
        idpartida=partida,
    ).select_related('idcarton')

    bolas_str = (partida.bolascantadas or '').replace('B', '').replace(
        'I', '').replace('N', '').replace('G', '').replace('O', '')
    bolas_llamadas = [int(b.strip())
                      for b in bolas_str.split(',') if b.strip().isdigit()]

    for asignacion in cartones_asignados:
        matriz = asignacion.idcarton.matriznumeros
        if isinstance(matriz, str):
            matriz = json.loads(matriz.replace("'", '"'))
        filas = []
        for i in range(5):
            fila = [matriz['B'][i], matriz['I'][i], matriz['N']
                    [i], matriz['G'][i], matriz['O'][i]]
            filas.append(fila)
        asignacion.filas_matriz = filas

    jugadores_en_sala = Jugador.objects.filter(
        sesionjuego__idpartida=partida,
        sesionjuego__estadosesion='Activa',
    ).distinct().order_by('aliasjugador')

    mensajes_historial = MensajeChat.objects.filter(
        idbingo=partida.idbingo).order_by('fechahora')

    contexto = {
        'partida': partida,
        'jugador': jugador,
        'cartones_asignados': cartones_asignados,
        'bolas_llamadas': bolas_llamadas,
        'jugadores_en_sala': jugadores_en_sala,
        'mensajes_historial': mensajes_historial,
        'horainicio_iso': partida.horainiciopartida.isoformat() if partida.horainiciopartida else timezone.now().isoformat(),
    }
    return render(request, 'partida/tablero_tiempo_real.html', contexto)


def obtener_ip_cliente(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


@login_required
def sesion_juego(request, id_partida):
    jugador = obtener_jugador_request(request)
    if not jugador:
        return redirect('registro_jugador')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)

    plataforma, _ = PlataformaJuego.objects.get_or_create(
        nombreplataforma='Web Oficial',
        defaults={
            'urlplataforma': request.build_absolute_uri('/'),
            'descripcionplataforma': 'Acceso nativo desde la aplicación web.',
            'estadoplataforma': True,
        }
    )

    user_agent = request.META.get('HTTP_USER_AGENT', 'Desconocido')

    dispositivo = 'PC / Escritorio'
    if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
        dispositivo = 'Dispositivo Móvil'
    elif 'iPad' in user_agent or 'Tablet' in user_agent:
        dispositivo = 'Tablet'

    navegador = 'Otro Navegador'
    if 'Chrome' in user_agent:
        navegador = 'Google Chrome'
    elif 'Safari' in user_agent and 'Chrome' not in user_agent:
        navegador = 'Apple Safari'
    elif 'Firefox' in user_agent:
        navegador = 'Mozilla Firefox'
    elif 'Edge' in user_agent:
        navegador = 'Microsoft Edge'

    with transaction.atomic():
        SesionJuego.objects.filter(
            idjugador=jugador,
            idpartida=partida,
            estadosesion='Activa'
        ).update(
            estadosesion='Finalizada',
            fechafinsesion=timezone.now(),
            motivocierre='Nueva conexión establecida',
        )
        sesion = SesionJuego.objects.create(
            idplataforma=plataforma,
            idjugador=jugador,
            idpartida=partida,
            fechainiciosesion=timezone.now(),
            ipconexion=obtener_ip_cliente(request),
            dispositivoconexion=dispositivo,
            estadosesion='Activa',
            navegadorweb=navegador,
            tokenconexion=str(uuid.uuid4()),
        )

    return render(request, 'partida/secion_juego.html', {'partida': partida, 'sesion': sesion})


def estado_partida_json(request, id_partida):
    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)
    from django.http import JsonResponse as _JsonResponse
    return _JsonResponse({
        'estado': partida.estadopartida,
        'hay_desempate': partida.haydesempate,
        'ganador': partida.idjugadororganador.aliasjugador if partida.idjugadororganador else None,
        'premio_efectivo': str(partida.valorpremio),
    })


@login_required
def tablero_admin(request, id_partida):
    if not request.user.is_staff:
        messages.error(
            request, "Acceso denegado. Zona exclusiva de administración.")
        return redirect('inicio')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'iniciar_partida' and partida.estadopartida == 'Programada':
            partida.estadopartida = 'En Juego'
            partida.horainiciopartida = timezone.now()
            partida.save()

            bingo_padre = partida.idbingo
            if bingo_padre.estadobingo == 'Programado':
                bingo_padre.estadobingo = 'En Curso'
                bingo_padre.save()

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'bingo_partida_{partida.idpartidabingo}',
                {'type': 'evento_partida', 'datos': {
                    'evento': 'estado_cambiado', 'nuevo_estado': 'En Juego'}}
            )
            messages.success(
                request, "¡Pitazo inicial! La ronda ha comenzado y el Bingo está En Curso.")
            return redirect('tablero_admin', id_partida=partida.idpartidabingo)

    bolas_str = (partida.bolascantadas or '').replace('B', '').replace(
        'I', '').replace('N', '').replace('G', '').replace('O', '')
    bolas_llamadas = [int(b.strip())
                      for b in bolas_str.split(',') if b.strip().isdigit()]

    tablero_maestro = {
        'B': {'rango': range(1, 16),  'color': 'primary'},
        'I': {'rango': range(16, 31), 'color': 'danger'},
        'N': {'rango': range(31, 46), 'color': 'secondary'},
        'G': {'rango': range(46, 61), 'color': 'success'},
        'O': {'rango': range(61, 76), 'color': 'warning'},
    }

    jugadores_en_sala = Jugador.objects.filter(
        sesionjuego__idpartida=partida,
        sesionjuego__estadosesion='Activa',
    ).distinct().order_by('aliasjugador')

    contexto = {
        'partida': partida,
        'bolas_llamadas': bolas_llamadas,
        'tablero_maestro': tablero_maestro,
        'jugadores_en_sala': jugadores_en_sala,
    }
    return render(request, 'partida/tablero_admin.html', contexto)


@login_required
def desempate_admin(request, id_partida):
    if not request.user.is_staff:
        return redirect('inicio')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)
    channel_layer = get_channel_layer()

    if partida.estadopartida == 'En Juego':
        partida.estadopartida = 'Verificando'
        partida.save()
        async_to_sync(channel_layer.group_send)(
            f'bingo_partida_{id_partida}',
            {'type': 'evento_partida', 'datos': {
                'evento': 'estado_cambiado', 'nuevo_estado': 'Verificando'}}
        )

    if request.method == 'POST':
        decision = request.POST.get('decision_desempate')

        if decision == 'si':
            partida.estadopartida = 'Desempate'
            partida.haydesempate = True
            partida.save()
            async_to_sync(channel_layer.group_send)(
                f'bingo_partida_{id_partida}',
                {'type': 'evento_partida', 'datos': {
                    'evento': 'estado_cambiado', 'nuevo_estado': 'Desempate'}}
            )
            messages.info(
                request, "Modo Desempate Activado. Prepare la consola.")
            return redirect('consola_juego', id_partida=partida.idpartidabingo)

        elif decision == 'no':
            codigo_ganador = request.POST.get('codigo_ganador_unico')
            resultado = validar_carton_hibrido(
                codigo_ganador, partida.idpartidabingo)

            if resultado['existe'] and resultado['valido']:
                partida.estadopartida = 'Finalizada'
                partida.idjugadororganador_id = resultado['id_jugador']
                partida.horafin = timezone.now()
                partida.save()

                es_pozo_mayor = (partida.premiomaterial == '[POZO_MAYOR]')
                monto_a_pagar = partida.idbingo.premiomayor if es_pozo_mayor else partida.valorpremio

                if monto_a_pagar and monto_a_pagar > 0:
                    jugador_ganador = Jugador.objects.get(
                        idjugador=resultado['id_jugador'])
                    tipo_moneda = partida.idbingo.idunidadmonetaria.tipomoneda
                    if tipo_moneda == 'Efectivo':
                        jugador_ganador.saldocreditojugador += monto_a_pagar
                    else:
                        jugador_ganador.saldovirtualjugador += monto_a_pagar
                    jugador_ganador.save()

                if not es_pozo_mayor and partida.premiomaterial and partida.premiomaterial != 'Ninguno':
                    partida.estadopremiomaterial = 'Pendiente'
                partida.save()

                siguiente_partida = PartidaBingo.objects.filter(
                    idbingo=partida.idbingo,
                    idpartidabingo__gt=partida.idpartidabingo
                ).order_by('idpartidabingo').first()

                if siguiente_partida:
                    destino_admin = redirect(
                        'tablero_admin', id_partida=siguiente_partida.idpartidabingo)
                else:
                    bingo_actual = partida.idbingo
                    bingo_actual.estadobingo = 'Finalizado'
                    bingo_actual.save()
                    destino_admin = redirect('dashboard')

                id_siguiente = siguiente_partida.idpartidabingo if siguiente_partida else None
                async_to_sync(channel_layer.group_send)(
                    f'bingo_partida_{id_partida}',
                    {'type': 'evento_partida', 'datos': {
                        'evento': 'estado_cambiado',
                        'nuevo_estado': 'Finalizada',
                        'ganador': resultado['jugador'],
                        'id_siguiente_partida': id_siguiente,
                    }}
                )
                messages.success(
                    request, f"¡Partida finalizada! Ganador único asignado: {resultado['jugador']}")
                return destino_admin
            else:
                messages.error(
                    request, "El código ingresado no es válido o no completó el cartón.")
                return redirect('desempate_admin', id_partida=partida.idpartidabingo)

    patrones = {
        'Tabla Llena': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
        'Las Cuatro Esquinas': [0, 4, 20, 24],
        'En Diagonal': [0, 6, 12, 18, 24],
        'Forma de X': [0, 4, 6, 8, 12, 16, 18, 20, 24],
        'Forma de Cruz': [2, 7, 10, 11, 12, 13, 14, 17, 22],
        'Marco de Foto': [0, 1, 2, 3, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24],
        'Linea Vertical': [2, 7, 12, 17, 22],
        'Forma de L': [0, 5, 10, 15, 20, 21, 22, 23, 24],
        'Forma de C': [0, 1, 2, 3, 4, 5, 10, 15, 20, 21, 22, 23, 24],
        'Forma de T': [0, 1, 2, 3, 4, 7, 12, 17, 22],
        'Forma de U': [0, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24],
        'Forma de H': [0, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19, 20, 24],
        'Forma de Z': [0, 1, 2, 3, 4, 8, 12, 16, 20, 21, 22, 23, 24],
        'Forma de Flecha': [2, 6, 8, 12, 17, 22],
    }
    marcadas_requeridas = patrones.get(
        partida.modalidad_victoria, patrones['Tabla Llena'])

    jugadores_conectados_ids = Jugador.objects.filter(
        sesionjuego__idpartida=partida,
        sesionjuego__estadosesion='Activa',
    ).values_list('idjugador', flat=True)

    cartones_en_juego = CartonPartidaBingo.objects.filter(
        idpartida=partida,
        idjugador__in=jugadores_conectados_ids,
    ).select_related('idcarton', 'idjugador')

    import ast
    ganadores_web = []
    for c in cartones_en_juego:
        marcados_db = []
        if getattr(c, 'numerosmarcados', None):
            try:
                marcados_db = json.loads(c.numerosmarcados)
            except Exception:
                try:
                    marcados_db = ast.literal_eval(c.numerosmarcados)
                except Exception:
                    pass
        if not marcados_db:
            continue
        marcados_str = [str(num) for num in marcados_db]
        matriz = c.idcarton.matriznumeros
        if isinstance(matriz, str):
            try:
                matriz = json.loads(matriz.replace("'", '"'))
            except Exception:
                continue
        celdas = []
        for i in range(5):
            celdas.extend([matriz['B'][i], matriz['I'][i],
                          matriz['N'][i], matriz['G'][i], matriz['O'][i]])
        es_ganador = all(
            str(celdas[idx]) in marcados_str
            for idx in marcadas_requeridas if idx != 12
        )
        if es_ganador:
            ganadores_web.append(c)

    contexto = {
        'partida': partida,
        'ganadores_web': ganadores_web,
    }
    return render(request, 'partida/desempate_admin.html', contexto)


@login_required
def consola_juego(request, id_partida):
    if not request.user.is_staff:
        return redirect('inicio')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)

    if partida.estadopartida == 'Finalizada':
        messages.info(request, "Esta partida ya ha finalizado.")
        return redirect('dashboard')

    candidatos_ids = []
    if partida.idbingadores:
        candidatos_ids = [int(i)
                          for i in partida.idbingadores.split(',') if i.strip()]
    candidatos = Jugador.objects.filter(idjugador__in=candidatos_ids)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'agregar_candidato':
            codigo = request.POST.get('codigo_carton')
            resultado = validar_carton_hibrido(codigo, partida.idpartidabingo)
            if resultado['existe'] and resultado['valido']:
                nuevo_id = str(resultado['id_jugador'])
                ids_actuales = partida.idbingadores.split(
                    ',') if partida.idbingadores else []
                if nuevo_id not in ids_actuales:
                    partida.idbingadores = f"{partida.idbingadores},{nuevo_id}" if partida.idbingadores else nuevo_id
                    partida.save()
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'bingo_partida_{id_partida}',
                        {'type': 'evento_partida', 'datos': {
                            'evento': 'invitacion_vip', 'id_jugador': nuevo_id}}
                    )
                    messages.success(
                        request, f"¡Cartón verificado! {resultado['jugador']} agregado al desempate.")
                else:
                    messages.warning(
                        request, "Este jugador ya está en la lista de desempate.")
            else:
                messages.error(request, "Código inválido o cartón incompleto.")
            return redirect('consola_juego', id_partida=id_partida)

        elif action == 'registrar_tiro_desempate':
            id_jugador_tiro = request.POST.get('id_jugador_tiro')
            numero_tiro = int(request.POST.get('numero_tiro'))
            sorteo = partida.sorteodesempate or {}
            sorteo[str(id_jugador_tiro)] = numero_tiro
            partida.sorteodesempate = sorteo
            partida.save()
            ids_actuales = [str(i.strip()) for i in str(
                partida.idbingadores).split(',') if i.strip()]
            completado = all(c in sorteo for c in ids_actuales)
            if completado:
                ganador_id = max(sorteo, key=sorteo.get)
                ganador_numero = sorteo[ganador_id]
                ganador_obj = Jugador.objects.filter(
                    idjugador=int(ganador_id)).first()
                ganador_nombre = ganador_obj.aliasjugador if ganador_obj else "Jugador Oficial"
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'bingo_partida_{id_partida}',
                    {'type': 'evento_partida', 'datos': {
                        'evento': 'desempate_completado',
                        'ganador_id': ganador_id,
                        'ganador_numero': ganador_numero,
                        'ganador_nombre': ganador_nombre,
                    }}
                )
            from django.http import JsonResponse as _JsonResponse
            return _JsonResponse({'status': 'ok', 'completado': completado})

        elif action == 'resolver_desempate':
            ganador_id = request.POST.get('ganador_final')
            bola_mayor = request.POST.get('bola_mayor')
            if ganador_id and bola_mayor:
                partida.idjugadororganador_id = ganador_id
                partida.bolamayordesempate = bola_mayor
                partida.estadopartida = 'Finalizada'
                partida.horafin = timezone.now()
                partida.save()
                es_pozo_mayor = (partida.premiomaterial == '[POZO_MAYOR]')
                monto_a_pagar = partida.idbingo.premiomayor if es_pozo_mayor else partida.valorpremio
                if monto_a_pagar and monto_a_pagar > 0:
                    jugador_ganador = Jugador.objects.get(idjugador=ganador_id)
                    tipo_moneda = partida.idbingo.idunidadmonetaria.tipomoneda
                    if tipo_moneda == 'Efectivo':
                        jugador_ganador.saldocreditojugador += monto_a_pagar
                    else:
                        jugador_ganador.saldovirtualjugador += monto_a_pagar
                    jugador_ganador.save()
                if not es_pozo_mayor and partida.premiomaterial and partida.premiomaterial != 'Ninguno':
                    partida.estadopremiomaterial = 'Pendiente'
                partida.save()
                siguiente_partida = PartidaBingo.objects.filter(
                    idbingo=partida.idbingo, idpartidabingo__gt=partida.idpartidabingo
                ).order_by('idpartidabingo').first()
                if siguiente_partida:
                    destino_admin = redirect(
                        'tablero_admin', id_partida=siguiente_partida.idpartidabingo)
                else:
                    bingo_actual = partida.idbingo
                    bingo_actual.estadobingo = 'Finalizado'
                    bingo_actual.save()
                    destino_admin = redirect('dashboard')
                id_siguiente = siguiente_partida.idpartidabingo if siguiente_partida else None
                ganador_obj = Jugador.objects.get(idjugador=ganador_id)
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'bingo_partida_{id_partida}',
                    {'type': 'evento_partida', 'datos': {
                        'evento': 'estado_cambiado',
                        'nuevo_estado': 'Finalizada',
                        'ganador': ganador_obj.aliasjugador,
                        'id_siguiente_partida': id_siguiente,
                    }}
                )
                messages.success(
                    request, "¡Desempate resuelto! El ganador ha sido registrado y la ronda ha finalizado.")
                return destino_admin
            else:
                messages.error(
                    request, "Debe seleccionar un ganador e ingresar la bola mayor.")
                return redirect('consola_juego', id_partida=id_partida)

    import ast
    patrones = {
        'Tabla Llena': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
        'Las Cuatro Esquinas': [0, 4, 20, 24],
        'En Diagonal': [0, 6, 12, 18, 24],
        'Forma de X': [0, 4, 6, 8, 12, 16, 18, 20, 24],
        'Forma de Cruz': [2, 7, 10, 11, 12, 13, 14, 17, 22],
        'Marco de Foto': [0, 1, 2, 3, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24],
        'Linea Vertical': [2, 7, 12, 17, 22],
        'Forma de L': [0, 5, 10, 15, 20, 21, 22, 23, 24],
        'Forma de C': [0, 1, 2, 3, 4, 5, 10, 15, 20, 21, 22, 23, 24],
        'Forma de T': [0, 1, 2, 3, 4, 7, 12, 17, 22],
        'Forma de U': [0, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24],
        'Forma de H': [0, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19, 20, 24],
        'Forma de Z': [0, 1, 2, 3, 4, 8, 12, 16, 20, 21, 22, 23, 24],
        'Forma de Flecha': [2, 6, 8, 12, 17, 22],
    }
    marcadas_requeridas = patrones.get(
        partida.modalidad_victoria, patrones['Tabla Llena'])
    jugadores_conectados_ids = Jugador.objects.filter(
        sesionjuego__idpartida=partida, sesionjuego__estadosesion='Activa',
    ).values_list('idjugador', flat=True)
    cartones_en_juego = CartonPartidaBingo.objects.filter(
        idpartida=partida, idjugador__in=jugadores_conectados_ids,
    ).select_related('idcarton', 'idjugador')
    ganadores_web = []
    for c in cartones_en_juego:
        marcados_db = []
        if getattr(c, 'numerosmarcados', None):
            try:
                marcados_db = json.loads(c.numerosmarcados)
            except Exception:
                try:
                    marcados_db = ast.literal_eval(c.numerosmarcados)
                except Exception:
                    pass
        if not marcados_db:
            continue
        marcados_str = [str(n) for n in marcados_db]
        matriz = c.idcarton.matriznumeros
        if isinstance(matriz, str):
            try:
                matriz = json.loads(matriz.replace("'", '"'))
            except Exception:
                continue
        celdas = []
        for i in range(5):
            celdas.extend([matriz['B'][i], matriz['I'][i],
                          matriz['N'][i], matriz['G'][i], matriz['O'][i]])
        if all(str(celdas[idx]) in marcados_str for idx in marcadas_requeridas if idx != 12):
            ganadores_web.append(c)

    contexto = {
        'partida': partida,
        'candidatos': candidatos,
        'ganadores_web': ganadores_web,
    }
    return render(request, 'partida/consola_juego.html', contexto)


@login_required
def sacar_bola_api(request, id_partida):
    if request.method != 'POST':
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Método no permitido'}, status=405)

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)
    from django.http import JsonResponse as _JR

    if partida.estadopartida != 'En Juego':
        return _JR({'error': 'La partida no está en curso'}, status=400)

    nueva_bola = avanzar_partida_con_bola(id_partida, enviar_evento=True)

    if nueva_bola is None:
        siguiente = PartidaBingo.objects.filter(
            idbingo=partida.idbingo,
            idpartidabingo__gt=partida.idpartidabingo,
        ).order_by('idpartidabingo').first()
        return _JR({
            'status': 'ok',
            'bola_extraida': None,
            'partida_finalizada': True,
            'id_siguiente_partida': siguiente.idpartidabingo if siguiente else None,
        })

    return _JR({'status': 'ok', 'bola_extraida': nueva_bola})


@login_required
def venta_cartones(request):
    """Alias a la función venta_cartones implementada más abajo"""
    # Esta es la versión simplificada que redirige a la implementación completa
    jugador = obtener_jugador_request(request)
    if not jugador:
        messages.warning(
            request, "Debes activar tu perfil de juego para entrar a la tienda.")
        return redirect('registro_jugador')

    if jugador.estadocuentajugador != 'Activo':
        messages.error(
            request, "Tu cuenta de jugador se encuentra suspendida o inactiva. No puedes realizar compras.")
        return redirect('inicio')

    if request.method == 'POST':
        id_bingo = request.POST.get('id_bingo')
        bingo = get_object_or_404(Bingo, idbingo=id_bingo)

        partidas_bingo = PartidaBingo.objects.filter(idbingo=bingo)
        if not partidas_bingo.exists() or partidas_bingo.exclude(estadopartida='Programada').exists():
            messages.error(
                request,
                "Solo puedes comprar cartones cuando las partidas del bingo estén en sala de espera.",
            )
            return redirect('venta_cartones')

        cartones_catalogo_ids = request.POST.getlist('cartones_catalogo')
        cartones_generados_json = request.POST.get('cartones_generados', '[]')

        try:
            cartones_generados = json.loads(cartones_generados_json)
        except Exception:
            cartones_generados = []

        cantidad_total_compra = len(
            cartones_catalogo_ids) + len(cartones_generados)

        if cantidad_total_compra == 0:
            messages.error(
                request, "No seleccionaste ni generaste ningún cartón para comprar.")
            return redirect('venta_cartones')

        cartones_ya_comprados = CartonPartidaBingo.objects.filter(
            idjugador=jugador, idpartida__idbingo=bingo).values('idcarton').distinct().count()

        precio_unitario = bingo.preciocarton
        total_pagar = precio_unitario * cantidad_total_compra

        if jugador.saldocreditojugador < total_pagar:
            messages.error(
                request, f"Fondos insuficientes. El total es ${total_pagar} y dispones de ${jugador.saldocreditojugador}.")
            return redirect('venta_cartones')

        partidas = partidas_bingo
        cartones_a_asignar = []

        if cartones_catalogo_ids:
            usados = CartonPartidaBingo.objects.filter(
                idpartida__in=partidas, idcarton__in=cartones_catalogo_ids).exists()
            if usados:
                messages.error(
                    request, "Oops. Un jugador más rápido compró uno de los cartones de catálogo que elegiste. Vuelve a intentarlo.")
                return redirect('venta_cartones')
            catalogo_validos = Carton.objects.filter(
                idcarton__in=cartones_catalogo_ids)
            cartones_a_asignar.extend(list(catalogo_validos))

        if cartones_generados:
            nuevos_cartones_db = [Carton(
                codigocarton=c_data['codigo'], matriznumeros=c_data['matriz'], esmaestro=False) for c_data in cartones_generados]
            Carton.objects.bulk_create(nuevos_cartones_db)
            codigos_creados = [c['codigo'] for c in cartones_generados]
            cartones_temporales = Carton.objects.filter(
                codigocarton__in=codigos_creados)
            cartones_a_asignar.extend(list(cartones_temporales))

        try:
            jugador.saldocreditojugador -= total_pagar
            jugador.save()

            nuevas_asignaciones = []
            for carton in cartones_a_asignar:
                for partida in partidas:
                    nuevas_asignaciones.append(CartonPartidaBingo(idjugador=jugador, idpartida=partida, idcarton=carton,
                                               preciopagado=precio_unitario, estadocarton='Vendido', fechacompra=datetime.now()))

            if nuevas_asignaciones:
                CartonPartidaBingo.objects.bulk_create(nuevas_asignaciones)

            # Notificar en tiempo real
            channel_layer = get_channel_layer()
            for carton in cartones_a_asignar:
                async_to_sync(channel_layer.group_send)(
                    f'bingo_tienda_{bingo.idbingo}',
                    {
                        'type': 'evento_tienda',
                        'datos': {
                            'evento': 'carton_vendido',
                            'id_carton': carton.idcarton
                        }
                    }
                )

            messages.success(
                request, f"¡Adrenalina pura! Tus {cantidad_total_compra} cartones han sido registrados en la base de datos para el evento '{bingo.titulobingo}'.")
            return redirect('venta_cartones')

        except Exception as e:
            messages.error(
                request, f"Fallo crítico en la transacción: {str(e)}")
            return redirect('venta_cartones')

    bingos_disponibles = Bingo.objects.exclude(estadobingo__in=[
                                               'Finalizado', 'Cancelado']).filter(partidabingo__isnull=False).distinct()
    bingos_data = []
    for b in bingos_disponibles:
        partidas_bingo = PartidaBingo.objects.filter(idbingo=b)
        if not partidas_bingo.exists() or partidas_bingo.exclude(estadopartida='Programada').exists():
            continue

        comprados = CartonPartidaBingo.objects.filter(
            idjugador=jugador, idpartida__idbingo=b).values('idcarton').distinct().count()
        porcentaje_barra = min(int((comprados / 15) * 100), 100)
        usados_ids = CartonPartidaBingo.objects.filter(
            idpartida__idbingo=b).values_list('idcarton', flat=True)
        catalogo = Carton.objects.filter(
            esmaestro=True).exclude(idcarton__in=usados_ids)[:12]

        bingos_data.append({'bingo': b, 'comprados': comprados,
                           'porcentaje': porcentaje_barra, 'catalogo': catalogo})

    contexto = {'jugador': jugador, 'bingos_data': bingos_data}
    return render(request, 'negocio/venta_cartones.html', contexto)


@login_required
def ventana_cartones(request, id_partida):
    """
    Vista para comprar cartones para una partida específica
    """
    jugador = obtener_jugador_request(request)
    if not jugador:
        messages.warning(
            request, "Necesitas crear tu perfil de jugador para comprar cartones.")
        return redirect('registro_jugador')

    if jugador.estadocuentajugador != 'Activo':
        messages.error(
            request, "Tu cuenta está suspendida. No puedes comprar cartones.")
        return redirect('inicio')

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)
    bingo = partida.idbingo

    if partida.estadopartida != 'Programada':
        messages.warning(
            request,
            "La compra de cartones solo está habilitada en sala de espera.",
        )
        return redirect('partidas')

    # Contar cartones ya comprados para esta partida
    cartones_ya_comprados = CartonPartidaBingo.objects.filter(
        idjugador=jugador,
        idpartida=partida
    ).count()

    # Cartones disponibles (maestros no usados)
    usados_ids = CartonPartidaBingo.objects.filter(
        idpartida=partida
    ).values_list('idcarton', flat=True)

    cartones_disponibles = Carton.objects.filter(
        esmaestro=True
    ).exclude(idcarton__in=usados_ids)[:20]

    contexto = {
        'jugador': jugador,
        'partida': partida,
        'bingo': bingo,
        'cartones_ya_comprados': cartones_ya_comprados,
        'cartones_disponibles': cartones_disponibles,
        'precio_unitario': bingo.preciocarton,
        'saldo_jugador': jugador.saldocreditojugador,
    }
    return render(request, 'negocio/ventana_cartones.html', contexto)


@login_required
def compra_carton_api(request, id_partida):
    """
    API para comprar cartones de una partida específica
    POST: {'cartones': [id1, id2, ...], 'cantidad': int}
    """
    if request.method != 'POST':
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Método no permitido'}, status=405)

    jugador = obtener_jugador_request(request)
    if not jugador:
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Jugador no encontrado'}, status=404)

    if jugador.estadocuentajugador != 'Activo':
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Cuenta suspendida'}, status=403)

    partida = get_object_or_404(PartidaBingo, idpartidabingo=id_partida)
    bingo = partida.idbingo

    if partida.estadopartida != 'Programada':
        from django.http import JsonResponse as _JR
        return _JR({'error': 'La compra de cartones solo está habilitada en sala de espera'}, status=409)

    try:
        data = json.loads(request.body)
        cartones_ids = data.get('cartones', [])
        cantidad_nueva = data.get('cantidad', 0)
    except:
        from django.http import JsonResponse as _JR
        return _JR({'error': 'JSON inválido'}, status=400)

    if not cartones_ids and cantidad_nueva <= 0:
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Debes seleccionar cartones o indicar cantidad'}, status=400)

    # ========== VALIDAR DISPONIBILIDAD ==========
    cartones_catalog = []
    if cartones_ids:
        cartones_catalog = list(Carton.objects.filter(
            idcarton__in=cartones_ids, esmaestro=True))

        # Verificar que no estén vendidos
        usados = CartonPartidaBingo.objects.filter(
            idpartida=partida,
            idcarton__in=cartones_ids
        ).exists()

        if usados:
            from django.http import JsonResponse as _JR
            return _JR({'error': 'Uno o más cartones ya fueron vendidos'}, status=409)

    # ========== CALCULAR TOTAL ==========
    cantidad_total = len(cartones_catalog) + cantidad_nueva
    precio_unitario = bingo.preciocarton
    total_pagar = precio_unitario * cantidad_total

    # ========== VALIDAR SALDO ==========
    if jugador.saldocreditojugador < total_pagar:
        from django.http import JsonResponse as _JR
        return _JR({
            'error': 'Fondos insuficientes',
            'saldo_actual': str(jugador.saldocreditojugador),
            'total_requerido': str(total_pagar),
            'faltante': str(total_pagar - jugador.saldocreditojugador)
        }, status=402)

    # ========== GENERAR CARTONES NUEVOS ==========
    cartones_a_asignar = list(cartones_catalog)

    if cantidad_nueva > 0:
        nuevos_cartones = []
        for i in range(cantidad_nueva):
            matriz_info = generar_lote_cartones(1)[0]
            matriz = matriz_info.get('matriz', {})
            codigo = f"GEN_{partida.idpartidabingo}_{jugador.idjugador}_{i}_{uuid.uuid4().hex[:8]}"
            nuevo_carton = Carton(
                codigocarton=codigo,
                matriznumeros=matriz,
                esmaestro=False
            )
            nuevos_cartones.append(nuevo_carton)

        Carton.objects.bulk_create(nuevos_cartones)
        cartones_a_asignar.extend(nuevos_cartones)

    # ========== PROCESAR COMPRA ==========
    try:
        with transaction.atomic():
            # Descontar del saldo
            jugador.saldocreditojugador -= total_pagar
            jugador.save()

            # Crear registros de CartonPartidaBingo
            asignaciones = []
            ahora = timezone.now()
            for carton in cartones_a_asignar:
                asignaciones.append(
                    CartonPartidaBingo(
                        idjugador=jugador,
                        idpartida=partida,
                        idcarton=carton,
                        preciopagado=precio_unitario,
                        estadocarton='Vendido',
                        fechacompra=ahora
                    )
                )

            CartonPartidaBingo.objects.bulk_create(asignaciones)

            # Notificar a otros juegan dores (WebSocket)
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'bingo_partida_{id_partida}',
                {
                    'type': 'evento_partida',
                    'datos': {
                        'evento': 'cartones_vendidos',
                        'jugador': jugador.aliasjugador,
                        'cantidad': cantidad_total,
                        'total_pago': str(total_pagar)
                    }
                }
            )

        from django.http import JsonResponse as _JR
        return _JR({
            'status': 'ok',
            'mensaje': f'¡Compra exitosa! {cantidad_total} cartones adquiridos',
            'cantidad': cantidad_total,
            'total_pagado': str(total_pagar),
            'saldo_restante': str(jugador.saldocreditojugador)
        }, status=200)

    except Exception as e:
        from django.http import JsonResponse as _JR
        return _JR({
            'error': f'Error en la compra: {str(e)}'
        }, status=500)


# ==========================================
# RECARGA DE SALDO
# ==========================================

@login_required
def recargar_saldo(request):
    """
    Página para recargar saldo/crédito del jugador
    """
    jugador = obtener_jugador_request(request)
    if not jugador:
        messages.warning(request, "Necesitas crear tu perfil de jugador.")
        return redirect('registro_jugador')

    # Montos predefinidos para seleccionar
    montos_predefinidos = [
        {'valor': Decimal('10.00'), 'label': '$10'},
        {'valor': Decimal('25.00'), 'label': '$25'},
        {'valor': Decimal('50.00'), 'label': '$50'},
        {'valor': Decimal('100.00'), 'label': '$100'},
        {'valor': Decimal('250.00'), 'label': '$250'},
        {'valor': Decimal('500.00'), 'label': '$500'},
    ]

    contexto = {
        'jugador': jugador,
        'saldo_actual': jugador.saldocreditojugador,
        'montos_predefinidos': montos_predefinidos,
    }
    return render(request, 'negocio/recargar_saldo.html', contexto)


@login_required
def procesar_recarga_saldo(request):
    """
    API para procesar la recarga de saldo
    POST: {'monto': float}
    """
    if request.method != 'POST':
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Método no permitido'}, status=405)

    jugador = obtener_jugador_request(request)
    if not jugador:
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Jugador no encontrado'}, status=404)

    try:
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body.decode('utf-8') or '{}')
        else:
            data = request.POST.dict()

        monto_str = data.get('monto', '0')
        monto = Decimal(str(monto_str))
    except Exception:
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Monto inválido'}, status=400)

    # Validar monto
    if monto <= 0:
        from django.http import JsonResponse as _JR
        return _JR({'error': 'El monto debe ser mayor a $0'}, status=400)

    if monto > Decimal('5000.00'):
        from django.http import JsonResponse as _JR
        return _JR({'error': 'Límite máximo de recarga: $5000'}, status=400)

    # ========== PROCESAR RECARGA ==========
    try:
        with transaction.atomic():
            saldo_anterior = jugador.saldocreditojugador
            jugador.saldocreditojugador += monto
            jugador.save()

            from django.http import JsonResponse as _JR
            return _JR({
                'status': 'ok',
                'mensaje': f'¡Recarga exitosa! Se agregaron ${monto}',
                'monto_recargado': str(monto),
                'saldo_anterior': str(saldo_anterior),
                'saldo_nuevo': str(jugador.saldocreditojugador)
            }, status=200)

    except Exception as e:
        from django.http import JsonResponse as _JR
        return _JR({'error': f'Error en la recarga: {str(e)}'}, status=500)


def bingo_publico(request):
    # Traemos los bingos que están por jugarse o en vivo (Para vender/promocionar)
    bingos_activos = Bingo.objects.filter(
        estadobingo__in=['Programado', 'En Curso']
    ).order_by('fechaprogramadabingo')

    # Traemos los bingos que ya terminaron (Historial)
    bingos_pasados = Bingo.objects.filter(
        estadobingo__in=['Finalizado', 'Cancelado']
        # Ordenados del más reciente al más antiguo
    ).order_by('-fechaprogramadabingo')

    # ================================================================
    # LÓGICA DE SALA DE ESPERA: Sincronizada con el inicio
    # ================================================================
    ahora = timezone.now()

    for b in bingos_activos:
        if b.fechaprogramadabingo:
            hora_apertura = b.fechaprogramadabingo - timedelta(minutes=30)
            partida_activa = PartidaBingo.objects.filter(
                idbingo=b,
                estadopartida__in=['Programada', 'En Juego']
            ).order_by('idpartidabingo').first()

            if ahora >= hora_apertura and partida_activa:
                b.sala_abierta = True
                b.id_partida_a_entrar = partida_activa.idpartidabingo
            else:
                b.sala_abierta = False
        else:
            b.sala_abierta = False

    mis_asignaciones = []
    if request.user.is_authenticated:
        jugador = obtener_jugador_request(request)
        if jugador:
            mis_asignaciones = CartonPartidaBingo.objects.filter(
                idjugador=jugador,
                idpartida__idbingo__estadobingo__in=['Programado', 'En Curso']
            ).select_related('idcarton', 'idpartida__idbingo').order_by('-fechacompra')

    contexto = {
        'bingos_activos': bingos_activos,
        'bingos_pasados': bingos_pasados,
        'unidad_monetaria': UnidadMonetaria.objects.first(),
        'mis_asignaciones': mis_asignaciones,
    }
    return render(request, 'comunes/bingo.html', contexto)


@login_required
def dashboard(request):
    if not request.user.is_staff:
        messages.error(
            request, "Acceso exclusivo para el personal de administración.")
        return redirect('inicio')

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'crear_tiposocio':
                TipoSocio.objects.create(nombretiposocio=request.POST.get('nombretiposocio'), roltiposocio=request.POST.get(
                    'roltiposocio'), descripciondetiposocio=request.POST.get('descripciondetiposocio'))
                messages.success(
                    request, "Tipo de Socio creado correctamente.")
            elif action == 'eliminar_tiposocio':
                TipoSocio.objects.get(
                    idtiposocio=request.POST.get('id_tipo')).delete()
                messages.success(request, "Tipo de Socio eliminado.")
            elif action == 'crear_plataforma':
                estado_plat = True if request.POST.get(
                    'estadoplataforma') == 'on' else False
                PlataformaJuego.objects.create(nombreplataforma=request.POST.get('nombreplataforma'), urlplataforma=request.POST.get('urlplataforma'), descripcionplataforma=request.POST.get('descripcionplataforma'), contactoplataforma=request.POST.get(
                    'contactoplataforma'), estadoplataforma=estado_plat, fechaadquisicionlicencia=request.POST.get('fechaadquisicionlicencia') or None, fechavencimientolicencia=request.POST.get('fechavencimientolicencia') or None, logoplataforma=request.FILES.get('logoplataforma'))
                messages.success(
                    request, "Plataforma de Juego registrada con éxito.")
            elif action == 'eliminar_plataforma':
                PlataformaJuego.objects.get(
                    idplataformajuego=request.POST.get('id_plataforma')).delete()
                messages.success(request, "Plataforma eliminada del sistema.")
            elif action == 'crear_bingo':
                unidad = get_object_or_404(
                    UnidadMonetaria, idunidad=request.POST.get('idunidadmonetaria'))
                Bingo.objects.create(idunidadmonetaria=unidad, titulobingo=request.POST.get('titulobingo'), fechaprogramadabingo=request.POST.get('fechaprogramadabingo'), tipobingo=request.POST.get('tipobingo'), lugarbingo=request.POST.get('lugarbingo'), urlsesionbingo=request.POST.get('urlsesionbingo'), preciocarton=request.POST.get(
                    'preciocarton'), premiomayor=request.POST.get('premiomayor'), descripcionpremiomayor=request.POST.get('descripcionpremiomayor'), estadobingo=request.POST.get('estadobingo'), descripcionpremios=request.POST.get('descripcionpremios'), rutaimagenpremiomayor=request.FILES.get('rutaimagenpremiomayor'), urlvideopromocional=request.FILES.get('urlvideopromocional'))
                messages.success(
                    request, "¡Jornada de Bingo creada exitosamente!")

            elif action == 'editar_bingo':
                bingo = Bingo.objects.get(idbingo=request.POST.get('id_bingo'))
                bingo.idunidadmonetaria = get_object_or_404(
                    UnidadMonetaria, idunidad=request.POST.get('idunidadmonetaria'))
                bingo.titulobingo = request.POST.get('titulobingo')
                bingo.preciocarton = request.POST.get('preciocarton')
                bingo.premiomayor = request.POST.get('premiomayor')
                bingo.descripcionpremiomayor = request.POST.get(
                    'descripcionpremiomayor')
                bingo.descripcionpremios = request.POST.get(
                    'descripcionpremios')
                if request.POST.get('fechaprogramadabingo'):
                    bingo.fechaprogramadabingo = request.POST.get(
                        'fechaprogramadabingo')
                bingo.tipobingo = request.POST.get('tipobingo')
                bingo.lugarbingo = request.POST.get('lugarbingo')
                bingo.urlsesionbingo = request.POST.get('urlsesionbingo')
                estado_anterior = bingo.estadobingo
                nuevo_estado = request.POST.get('estadobingo')
                bingo.estadobingo = nuevo_estado
                if 'rutaimagenpremiomayor' in request.FILES:
                    bingo.rutaimagenpremiomayor = request.FILES['rutaimagenpremiomayor']
                if 'urlvideopromocional' in request.FILES:
                    bingo.urlvideopromocional = request.FILES['urlvideopromocional']
                bingo.save()

                # ==========================================================
                # ÁRBITRO DIGITAL: DISPARO INICIAL (Variables Corregidas)
                # ==========================================================
                if nuevo_estado == 'En Curso' and estado_anterior != 'En Curso':
                    primera_partida = PartidaBingo.objects.filter(
                        idbingo=bingo).order_by('idpartidabingo').first()
                    if primera_partida and primera_partida.estadopartida == 'Programada':
                        primera_partida.estadopartida = 'En Juego'
                        primera_partida.horainiciopartida = timezone.now()  # CORREGIDO A horainiciopartida
                        primera_partida.save()
                        messages.success(
                            request, "¡Bingo iniciado! La primera ronda ha comenzado automáticamente.")
                # ==========================================================

                if nuevo_estado == 'Finalizado' and estado_anterior != 'Finalizado':
                    cartones_temporales = CartonPartidaBingo.objects.filter(
                        idpartida__idbingo=bingo, idcarton__esmaestro=False).values_list('idcarton', flat=True)
                    ids_a_borrar = list(set(cartones_temporales))
                    if ids_a_borrar:
                        CartonPartidaBingo.objects.filter(
                            idpartida__idbingo=bingo, idcarton__esmaestro=False).delete()
                        Carton.objects.filter(
                            idcarton__in=ids_a_borrar).delete()
                        messages.success(
                            request, f"¡Bingo Finalizado! El sistema ha autodestruido {len(ids_a_borrar)} cartones temporales.")
                    else:
                        messages.success(
                            request, "Jornada de Bingo actualizada y Finalizada correctamente.")
                else:
                    messages.success(
                        request, "Jornada de Bingo actualizada correctamente.")

            elif action == 'eliminar_bingo':
                Bingo.objects.get(
                    idbingo=request.POST.get('id_bingo')).delete()
                messages.success(
                    request, "Jornada de Bingo eliminada por completo.")

            elif action == 'crear_partida':
                bingo_obj = Bingo.objects.get(
                    idbingo=request.POST.get('idbingo'))

                # FIX FASE 2: LÓGICA DEL PREMIO MAYOR ÚNICO
                es_pozo_mayor = request.POST.get('es_pozo_mayor') == 'on'

                if es_pozo_mayor:
                    valor_premio = 0
                    # Etiqueta secreta para el motor de pagos
                    premio_material = '[POZO_MAYOR]'
                else:
                    valor_premio = request.POST.get('valorpremio')
                    premio_material = request.POST.get('premiomaterial')
                    if not valor_premio or str(valor_premio).strip() == '':
                        valor_premio = 0
                    if not premio_material or str(premio_material).strip() == '':
                        premio_material = 'Ninguno'

                PartidaBingo.objects.create(
                    idbingo=bingo_obj,
                    nombreronda=request.POST.get('nombreronda'),
                    modalidad_victoria=request.POST.get(
                        'modalidad_victoria', 'Tabla Llena'),
                    valorpremio=valor_premio,
                    premiomaterial=premio_material,
                    estadopartida='Programada',
                    bolascantadas='',
                    ultimabola=0
                )

                if es_pozo_mayor:
                    messages.success(
                        request, f"¡Ronda '{request.POST.get('nombreronda')}' aperturada! Jugarán por el POZO MAYOR de ${bingo_obj.premiomayor}.")
                else:
                    messages.success(
                        request, f"¡Ronda '{request.POST.get('nombreronda')}' aperturada con modalidad {request.POST.get('modalidad_victoria')}!")

            elif action == 'eliminar_partida':
                PartidaBingo.objects.get(
                    idpartidabingo=request.POST.get('id_partida')).delete()
                messages.success(request, "Ronda eliminada de forma segura.")
            # =======================================================
            # NUEVO: LOGÍSTICA DE ENTREGA DE PREMIOS FÍSICOS
            # =======================================================
            elif action == 'entregar_premio_fisico':
                partida = PartidaBingo.objects.get(
                    idpartidabingo=request.POST.get('id_partida'))
                partida.estadopremiomaterial = 'Entregado'
                partida.save()
                messages.success(
                    request, f"¡Excelente! El premio físico de la ronda '{partida.nombreronda}' ha sido marcado como ENTREGADO.")
            # =======================================================
            elif action == 'editar_configuracion':
                config, created = ConfiguracionWeb.objects.get_or_create(
                    idconfiguracion=1)
                config.titulosobrenosotros = request.POST.get(
                    'titulosobrenosotros', config.titulosobrenosotros)
                config.descripcionsobrenosotros = request.POST.get(
                    'descripcionsobrenosotros', config.descripcionsobrenosotros)
                config.numerowhatsapp = request.POST.get(
                    'numerowhatsapp', config.numerowhatsapp)
                config.enlaceinstagram = request.POST.get(
                    'enlaceinstagram', config.enlaceinstagram)
                config.enlacefacebook = request.POST.get(
                    'enlacefacebook', config.enlacefacebook)
                if 'imagenpromocional' in request.FILES:
                    config.imagenpromocional = request.FILES['imagenpromocional']
                config.save()
                messages.success(
                    request, "Configuración del sitio web actualizada correctamente.")
            elif action == 'generar_cartones':
                cantidad = int(request.POST.get('cantidad_cartones', 0))
                if cantidad > 0:
                    lote = generar_lote_cartones(cantidad)
                    cartones_db = [Carton(
                        codigocarton=c['codigo'], matriznumeros=c['matriz'], esmaestro=True) for c in lote]
                    Carton.objects.bulk_create(cartones_db)
                    fabricar_cartones_maestros_task.delay(cantidad)
                    messages.success(
                        request, f"¡Orden enviada a la fábrica! Se están estampando {cantidad} cartones RNG en segundo plano.")
            elif action == 'eliminar_carton':
                Carton.objects.get(
                    idcarton=request.POST.get('id_carton')).delete()
                messages.success(
                    request, "Cartón retirado del inventario general.")
            elif action == 'editar_socio':
                actualizar_socio_y_credenciales(request.POST.get('id_socio'), request.POST.get('cedula'), request.POST.get('nombres'), request.POST.get(
                    'apellidos'), request.POST.get('telefono'), request.POST.get('estado'), request.POST.get('id_tipo_socio'), request.POST.get('password_nueva'))
                messages.success(
                    request, f"Perfil del socio actualizado correctamente.")
            elif action == 'editar_jugador':
                actualizar_jugador_y_credenciales(request.POST.get('id_jugador'), request.POST.get('alias'), request.POST.get(
                    'cedula'), request.POST.get('correo'), request.POST.get('estado'), request.POST.get('password_nueva'))
                messages.success(
                    request, f"Perfil del jugador actualizado correctamente.")
            elif action == 'aprobar_prestamo':
                id_prestamo = request.POST.get('id_prestamo')
                with transaction.atomic():
                    prestamo = Prestamo.objects.select_for_update().select_related('idsocio').get(
                        idprestamo=id_prestamo
                    )

                    if prestamo.estadoprestamo != 'Solicitado':
                        messages.warning(
                            request,
                            "Este préstamo ya fue procesado anteriormente.",
                        )
                    else:
                        socio = prestamo.idsocio
                        jugador = None

                        if not socio or not socio.cisocio:
                            messages.error(
                                request,
                                "No se pudo aprobar: el socio no tiene cédula válida para vincular el crédito.",
                            )
                        else:
                            # Prioridad 1: jugador vinculado al socio.
                            jugador = Jugador.objects.select_for_update().filter(
                                idsocio=socio
                            ).order_by('-idjugador').first()

                            # Prioridad 2: por cédula del socio (si aún no está vinculado).
                            if not jugador:
                                jugador = Jugador.objects.select_for_update().filter(
                                    cedulaidentidadjugador=socio.cisocio
                                ).order_by('-idjugador').first()

                            # Si se encontró por cédula y no está vinculado, lo vinculamos.
                            if jugador and not jugador.idsocio:
                                jugador.idsocio = socio
                                jugador.save(update_fields=['idsocio'])

                            # Si existe un jugador con esa cédula pero pertenece a otro socio, evitamos acreditar al perfil equivocado.
                            if jugador and jugador.idsocio and jugador.idsocio_id != socio.idsocio:
                                messages.error(
                                    request,
                                    "Conflicto de identidad detectado: la cédula del socio está asociada a otro perfil de jugador.",
                                )
                                jugador = None

                            if not jugador:
                                correo_usuario = User.objects.filter(
                                    username=socio.cisocio
                                ).values_list('email', flat=True).first()

                                correo_para_jugador = None
                                if correo_usuario and not Jugador.objects.filter(correojugador__iexact=correo_usuario).exists():
                                    correo_para_jugador = correo_usuario

                                alias_base = f"Socio{socio.cisocio[-4:]}"
                                alias_candidato = alias_base
                                indice_alias = 1
                                while Jugador.objects.filter(aliasjugador__iexact=alias_candidato).exists():
                                    indice_alias += 1
                                    alias_candidato = f"{alias_base}{indice_alias}"

                                jugador = Jugador.objects.create(
                                    idsocio=socio,
                                    nombresjugador=socio.primernombresocio,
                                    apellidosjugador=socio.primerapellidosocio,
                                    cedulaidentidadjugador=socio.cisocio,
                                    correojugador=correo_para_jugador,
                                    aliasjugador=alias_candidato,
                                    estadocuentajugador='Activo',
                                )

                            campos_actualizar_jugador = []
                            if not jugador.idsocio:
                                jugador.idsocio = socio
                                campos_actualizar_jugador.append('idsocio')
                            if not jugador.cedulaidentidadjugador:
                                cedula_en_uso = Jugador.objects.filter(
                                    cedulaidentidadjugador=socio.cisocio
                                ).exclude(idjugador=jugador.idjugador).exists()
                                if not cedula_en_uso:
                                    jugador.cedulaidentidadjugador = socio.cisocio
                                    campos_actualizar_jugador.append(
                                        'cedulaidentidadjugador')
                            if campos_actualizar_jugador:
                                jugador.save(
                                    update_fields=campos_actualizar_jugador)

                            jugador = consolidar_jugadores_duplicados(
                                socio,
                                jugador_preferido=jugador,
                            )

                            monto_base = Decimal(
                                prestamo.montoprestamosolicitado or 0)
                            if monto_base <= 0:
                                messages.error(
                                    request,
                                    "No se pudo aprobar: el monto solicitado no es válido.",
                                )
                            else:
                                tasa = Decimal(prestamo.tasainteres or 0)
                                interes = (monto_base * tasa) / Decimal('100')
                                total_pagar = prestamo.montototalpagar or (
                                    monto_base + interes)

                                prestamo.montototalpagar = total_pagar
                                prestamo.saldopendiente = total_pagar
                                prestamo.estadoprestamo = 'Aprobado'
                                if not prestamo.fechasolicitud:
                                    prestamo.fechasolicitud = timezone.now().date()
                                if not prestamo.fechavencimiento:
                                    cuotas = int(prestamo.numerocuotas or 1)
                                    prestamo.fechavencimiento = timezone.now().date() + timedelta(days=30 * cuotas)
                                prestamo.save()

                                jugador.saldocreditojugador += monto_base
                                jugador.save(update_fields=[
                                             'saldocreditojugador'])

                                messages.success(
                                    request,
                                    f"Préstamo #{prestamo.idprestamo} aprobado y acreditado: ${monto_base} a {jugador.aliasjugador or jugador.cedulaidentidadjugador}.",
                                )

            elif action == 'rechazar_prestamo':
                id_prestamo = request.POST.get('id_prestamo')
                prestamo = Prestamo.objects.get(idprestamo=id_prestamo)
                if prestamo.estadoprestamo != 'Solicitado':
                    messages.warning(
                        request,
                        "Este préstamo ya fue procesado anteriormente.",
                    )
                else:
                    prestamo.estadoprestamo = 'Rechazado'
                    prestamo.save(update_fields=['estadoprestamo'])
                    messages.info(
                        request,
                        f"Préstamo #{prestamo.idprestamo} rechazado correctamente.",
                    )
            elif action == 'crear_regalo':
                imagen_regalo = request.FILES.get('urlimagen')
                if not imagen_regalo:
                    messages.error(
                        request,
                        "Debes subir una imagen para registrar el regalo.",
                    )
                else:
                    Regalo.objects.create(
                        nombreregalo=request.POST.get('nombreregalo'),
                        descripcionregalo=request.POST.get(
                            'descripcionregalo'),
                        valorregalo=request.POST.get(
                            'valorregalo') or Decimal('0.00'),
                        estadoregalo='Acumulado',
                        urlimagen=imagen_regalo,
                    )
                    messages.success(
                        request,
                        "Regalo registrado en catálogo y listo para sorteo.",
                    )
            elif action == 'sortear_regalo':
                id_regalo = request.POST.get('id_regalo')
                with transaction.atomic():
                    regalo = Regalo.objects.select_for_update().get(
                        idregalo=id_regalo)

                    if regalo.estadoregalo != 'Acumulado':
                        messages.warning(
                            request,
                            "Este regalo ya fue sorteado o entregado.",
                        )
                    else:
                        candidatos = Socio.objects.filter(
                            estadosocio='Activo',
                            jugador__estadocuentajugador='Activo',
                        ).distinct().order_by('idsocio')

                        if not candidatos.exists():
                            messages.error(
                                request,
                                "No hay socios activos con perfil de jugador para el sorteo.",
                            )
                        else:
                            ganador_socio = random.choice(list(candidatos))
                            referencia = f"SORTEO_ADMIN_{request.user.username}_{uuid.uuid4().hex[:6].upper()}"
                            AporteSemanal.objects.create(
                                idsocio=ganador_socio,
                                idregalo=regalo,
                                idpartida=None,
                                numerosemana=timezone.now().isocalendar().week,
                                fechaplanificadadada=timezone.now(),
                                metodoingreso='Fisico',
                                referenciaingreso=referencia,
                                estadoaporte='Al Dia',
                            )
                            regalo.estadoregalo = 'Sorteado'
                            regalo.save(update_fields=['estadoregalo'])

                            messages.success(
                                request,
                                f"Sorteo exitoso: el regalo '{regalo.nombreregalo}' fue asignado al socio CI {ganador_socio.cisocio}.",
                            )
            elif action == 'entregar_regalo':
                id_regalo = request.POST.get('id_regalo')
                with transaction.atomic():
                    regalo = Regalo.objects.select_for_update().get(
                        idregalo=id_regalo)

                    if regalo.estadoregalo == 'Entregado':
                        messages.info(
                            request,
                            "Este regalo ya se encontraba marcado como entregado.",
                        )
                    else:
                        regalo.estadoregalo = 'Entregado'
                        regalo.fechaentregaregalo = timezone.now()
                        regalo.save(
                            update_fields=['estadoregalo', 'fechaentregaregalo'])

                        asignacion = AporteSemanal.objects.filter(
                            idregalo=regalo,
                        ).order_by('-idaporte').first()
                        if asignacion:
                            asignacion.fechaentregareal = timezone.now()
                            asignacion.save(update_fields=['fechaentregareal'])

                        messages.success(
                            request,
                            f"Regalo '{regalo.nombreregalo}' marcado como entregado.",
                        )
            elif action == 'crear_moneda':
                UnidadMonetaria.objects.create(
                    nombre=request.POST.get('nombremoneda'),
                    simbolo=request.POST.get('simbolomoneda'),
                )
                messages.success(
                    request, "Nueva unidad monetaria registrada con éxito.")

            elif action == 'editar_moneda':
                moneda = UnidadMonetaria.objects.get(
                    idunidad=request.POST.get('id_moneda'))
                moneda.nombre = request.POST.get('nombremoneda')
                moneda.simbolo = request.POST.get('simbolomoneda')
                moneda.save()
                messages.success(request, "Divisa actualizada correctamente.")

            elif action == 'eliminar_moneda':
                UnidadMonetaria.objects.get(
                    idunidad=request.POST.get('id_moneda')).delete()
                messages.success(request, "Divisa eliminada del sistema.")
        except ProtectedError:
            messages.error(
                request, "⚠️ ERROR: No puedes eliminar este registro porque hay usuarios o datos vinculados a él.")
        except Exception as e:
            messages.error(request, f"Error en la operación: {str(e)}")
        return redirect('dashboard')
    # ====================================================================
    # INSERCIÓN SEGURA: MOTOR ESTADÍSTICO PARA EL DASHBOARD
    # ====================================================================
    hoy = timezone.now()
    ayer = hoy - timedelta(days=1)
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)
    inicio_anio = hoy.replace(month=1, day=1)

    datos_graficos = {
        'hoy': {'socios': 0, 'jugadores': 0, 'ganancias': 0},
        'ayer': {'socios': 0, 'jugadores': 0, 'ganancias': 0},
        'semana': {'socios': 0, 'jugadores': 0, 'ganancias': 0},
        'mes': {'socios': 0, 'jugadores': 0, 'ganancias': 0},
        'anio': {'socios': 0, 'jugadores': 0, 'ganancias': 0},
    }

    try:
        # 1. Procesar Ganancias Reales (¡Usando la tabla Carton correcta!)
        cartones_db = Carton.objects.all()
        for c in cartones_db:
            # Buscamos el atributo correcto sin importar cómo se llame exactamente
            fecha_obj = getattr(c, 'fechacompra', getattr(
                c, 'fecha_creacion', getattr(c, 'fecha', None)))
            if fecha_obj:
                fecha = fecha_obj.date() if hasattr(fecha_obj, 'date') else fecha_obj
                monto = float(getattr(c, 'preciopagado', 0) or 0)

                if fecha == hoy.date():
                    datos_graficos['hoy']['ganancias'] += monto
                if fecha == ayer.date():
                    datos_graficos['ayer']['ganancias'] += monto
                if fecha >= inicio_semana.date():
                    datos_graficos['semana']['ganancias'] += monto
                if fecha >= inicio_mes.date():
                    datos_graficos['mes']['ganancias'] += monto
                if fecha >= inicio_anio.date():
                    datos_graficos['anio']['ganancias'] += monto

        # 2. Procesar Socios Registrados
        socios_db = Socio.objects.all()
        for s in socios_db:
            fecha = None
            if hasattr(s, 'idusuario') and s.idusuario and hasattr(s.idusuario, 'date_joined'):
                fecha = s.idusuario.date_joined.date()

            if fecha:
                if fecha == hoy.date():
                    datos_graficos['hoy']['socios'] += 1
                if fecha == ayer.date():
                    datos_graficos['ayer']['socios'] += 1
                if fecha >= inicio_semana.date():
                    datos_graficos['semana']['socios'] += 1
                if fecha >= inicio_mes.date():
                    datos_graficos['mes']['socios'] += 1
                if fecha >= inicio_anio.date():
                    datos_graficos['anio']['socios'] += 1
            else:
                for k in datos_graficos:
                    datos_graficos[k]['socios'] += 1

        # 3. Procesar Jugadores
        jugadores_db = Jugador.objects.all()
        for j in jugadores_db:
            fecha = None
            if hasattr(j, 'idusuario') and j.idusuario and hasattr(j.idusuario, 'date_joined'):
                fecha = j.idusuario.date_joined.date()

            if fecha:
                if fecha == hoy.date():
                    datos_graficos['hoy']['jugadores'] += 1
                if fecha == ayer.date():
                    datos_graficos['ayer']['jugadores'] += 1
                if fecha >= inicio_semana.date():
                    datos_graficos['semana']['jugadores'] += 1
                if fecha >= inicio_mes.date():
                    datos_graficos['mes']['jugadores'] += 1
                if fecha >= inicio_anio.date():
                    datos_graficos['anio']['jugadores'] += 1
            else:
                for k in datos_graficos:
                    datos_graficos[k]['jugadores'] += 1

    except Exception as e:
        # Si algo explota silenciosamente, lo ignoramos para NO TIRAR LA PÁGINA
        print(f"Error en el motor del gráfico: {e}")
    # ====================================================================

    contexto = {
        'total_socios': Socio.objects.count(), 'total_jugadores': Jugador.objects.count(), 'deuda_calle': Prestamo.objects.exclude(estadoprestamo='Liquidado').aggregate(total=Sum('saldopendiente'))['total'] or 0.00,
        'bingos_activos': Bingo.objects.exclude(estadobingo__in=['Finalizado', 'Cancelado']).count(), 'tipos_socio': TipoSocio.objects.all(),
        'socios': Socio.objects.all().order_by('-idsocio')[:50], 'accounts': CuentaBancaria.objects.all().select_related('idsocio'),
        'jugadores': Jugador.objects.all().order_by('-idjugador')[:50], 'prestamos': Prestamo.objects.all().order_by('-fechasolicitud')[:30],
        'pagos': Pago.objects.all().order_by('-fechapago')[:30], 'metodos_pago': MetodoPago.objects.all(),
        'ahorros': Ahorro.objects.all().order_by('-fechaahorro')[:30], 'aportes_semanales': AporteSemanal.objects.all().order_by('-fechaplanificadadada')[:30],
        'bingos': Bingo.objects.all().order_by('-fechaprogramadabingo'), 'partidas': PartidaBingo.objects.all(),
        'regalos': regalos_lista, 'cartones': Carton.objects.all().order_by('-idcarton')[:50],
        'cartones_en_juego': CartonPartidaBingo.objects.all()[:50], 'plataformas': PlataformaJuego.objects.all(),
        'sesiones_monitoreo': SesionJuego.objects.all().order_by('-fechainiciosesion')[:30], 'config_web': ConfiguracionWeb.objects.first(),
        'unidades_monetarias': UnidadMonetaria.objects.all(),
        'todas_monedas': UnidadMonetaria.objects.all(),
        'ultimas_asignaciones_regalo': ultimas_asignaciones_regalo,
        'ganador_por_regalo': ganador_por_regalo,

    }
    # Agrega esto al final de tus variables de contexto
    contexto['bingos_con_pozo'] = list(PartidaBingo.objects.filter(
        premiomaterial='[POZO_MAYOR]').values_list('idbingo_id', flat=True))

    # NUEVO: Le mandamos la información empaquetada en JSON al gráfico del HTML
    contexto['datos_graficos_json'] = json.dumps(datos_graficos)

    return render(request, 'administrador/dashboard.html', contexto)


@login_required
def reporte_socios_puntuales(request):
    if not request.user.is_staff:
        return redirect('inicio')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Socios Estrella"

    ws.append(['Cédula', 'Socio', 'Teléfono', 'Tipo de Socio',
              'Historial de Aportes', 'Calificación'])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="312E81",
                                fill_type="solid")  # Azul corporativo
        cell.alignment = Alignment(horizontal="center", vertical="center")

    socios = Socio.objects.filter(
        estadosocio='Activo').select_related('idtiposocio')
    for s in socios:
        aportes = AporteSemanal.objects.filter(idsocio=s)
        total_aportes = aportes.count()
        aportes_al_dia = aportes.filter(estadoaporte='Al Dia').count()

        clasificacion = "Sin Historial"
        if total_aportes > 0:
            porcentaje = (aportes_al_dia / total_aportes) * 100
            if porcentaje == 100:
                clasificacion = "🌟 EXCELENTE (Aplica Descuento)"
            elif porcentaje >= 80:
                clasificacion = "👍 BUENO (Cumplido)"
            elif porcentaje >= 50:
                clasificacion = "⚠️ REGULAR (Alerta)"
            else:
                clasificacion = "❌ MOROSO (Riesgo Alto)"

        ws.append([
            s.cisocio,
            f"{s.primernombresocio} {s.primerapellidosocio}",
            s.telefonopersonalsocio,
            s.idtiposocio.nombretiposocio if s.idtiposocio else "No Definido",
            f"{aportes_al_dia} de {total_aportes} Al Día",
            clasificacion
        ])

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[openpyxl.utils.get_column_letter(
            col[0].column)].width = max(max_len + 3, 12)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Socios_Estrella_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    wb.save(response)
    return response


@login_required
def reporte_liquidacion_bingo(request, id_bingo):
    if not request.user.is_staff:
        return redirect('inicio')

    bingo = get_object_or_404(Bingo, idbingo=id_bingo)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Liquidación de Bingo"

    ws.append(['Concepto', 'Detalle', 'Monto Total'])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1E1B4B", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Obtención de métricas mediante agregaciones en la base de datos
    cartones_vendidos = CartonPartidaBingo.objects.filter(
        idpartida__idbingo=bingo).values('idcarton').distinct().count()
    ingresos_totales = cartones_vendidos * bingo.preciocarton

    # Manejo adaptativo de campos por si la base varía el nombre del premio
    premios_entregados = 0
    try:
        premios_entregados = PartidaBingo.objects.filter(
            idbingo=bingo).aggregate(total=Sum('valorpremio'))['total'] or 0
    except:
        try:
            premios_entregados = PartidaBingo.objects.filter(
                idbingo=bingo).aggregate(total=Sum('valorefectivo'))['total'] or 0
        except:
            pass

    utilidad_neta = ingresos_totales - premios_entregados

    ws.append(
        ['INGRESOS', f'Recaudación por Cartones ({cartones_vendidos} x ${bingo.preciocarton})', ingresos_totales])
    ws.append(
        ['EGRESOS', 'Total Premios en Efectivo Entregados en Rondas', -premios_entregados])
    ws.append(['UTILIDAD LÍQUIDA', 'Balance Neto de la Cooperativa', utilidad_neta])

    ws[4][2].font = Font(
        bold=True, color="008000" if utilidad_neta >= 0 else "FF0000")
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 45
    ws.column_dimensions['C'].width = 18

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Liquidacion_{bingo.idbingo}_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    wb.save(response)
    return response


@login_required
def reporte_cartera_prestamos(request):
    if not request.user.is_staff:
        return redirect('inicio')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cartera de Créditos"

    ws.append(['Cédula', 'Socio', 'Monto Solicitado',
              'Total a Pagar', 'Saldo Pendiente', 'Estado'])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        # Rojo analítico financiero
        cell.fill = PatternFill(start_color="B91C1C", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    prestamos = Prestamo.objects.all().select_related(
        'idsocio').order_by('-fechasolicitud')
    for p in prestamos:
        ws.append([
            p.idsocio.cisocio if p.idsocio else "N/A",
            f"{p.idsocio.primernombresocio} {p.idsocio.primerapellidosocio}" if p.idsocio else "Externo",
            float(p.montoprestamosolicitado or 0),
            float(p.montototalpagar or 0),
            float(p.saldopendiente or 0),
            p.estadoprestamo
        ])

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[openpyxl.utils.get_column_letter(
            col[0].column)].width = max(max_len + 3, 12)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Cartera_Creditos_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    wb.save(response)
    return response


@login_required
def reporte_caja_semanal_pdf(request):
    if not request.user.is_staff:
        return redirect('inicio')

    aportes = AporteSemanal.objects.all().select_related('idsocio').order_by(
        '-fechaplanificadadada', 'idsocio__primerapellidosocio')
    total_recaudado = aportes.filter(estadoaporte='Al Dia').aggregate(
        total=Sum('montoaportesemanal'))['total'] or 0
    total_pendiente = aportes.filter(estadoaporte='Pendiente').aggregate(
        total=Sum('montoaportesemanal'))['total'] or 0

    template = get_template('administrador/reporte_caja_pdf.html')
    context = {
        'aportes': aportes,
        'total_recaudado': total_recaudado,
        'total_pendiente': total_pendiente,
        'fecha_reporte': timezone.now()
    }
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="Cierre_Caja_Semanal.pdf"'
    pisa.CreatePDF(html, dest=response)
    return response


@login_required
def venta_cartones(request):
    jugador = obtener_jugador_request(request)
    if not jugador:
        messages.warning(
            request, "Debes activar tu perfil de juego para entrar a la tienda.")
        return redirect('registro_jugador')

    if jugador.estadocuentajugador != 'Activo':
        messages.error(
            request, "Tu cuenta de jugador se encuentra suspendida o inactiva. No puedes realizar compras.")
        return redirect('inicio')

    if request.method == 'POST':
        id_bingo = request.POST.get('id_bingo')
        bingo = get_object_or_404(Bingo, idbingo=id_bingo)

        partidas_bingo = PartidaBingo.objects.filter(idbingo=bingo)
        if not partidas_bingo.exists() or partidas_bingo.exclude(estadopartida='Programada').exists():
            messages.error(
                request,
                "Solo puedes comprar cartones cuando las partidas del bingo estén en sala de espera.",
            )
            return redirect('venta_cartones')

        cartones_catalogo_ids = request.POST.getlist('cartones_catalogo')
        cartones_generados_json = request.POST.get('cartones_generados', '[]')

        try:
            cartones_generados = json.loads(cartones_generados_json)
        except Exception:
            cartones_generados = []

        cantidad_total_compra = len(
            cartones_catalogo_ids) + len(cartones_generados)

        if cantidad_total_compra == 0:
            messages.error(
                request, "No seleccionaste ni generaste ningún cartón para comprar.")
            return redirect('venta_cartones')

        cartones_ya_comprados = CartonPartidaBingo.objects.filter(
            idjugador=jugador, idpartida__idbingo=bingo).values('idcarton').distinct().count()

        precio_unitario = bingo.preciocarton
        total_pagar = precio_unitario * cantidad_total_compra

        if jugador.saldocreditojugador < total_pagar:
            messages.error(
                request, f"Fondos insuficientes. El total es ${total_pagar} y dispones de ${jugador.saldocreditojugador}.")
            return redirect('venta_cartones')

        partidas = partidas_bingo
        cartones_a_asignar = []

        if cartones_catalogo_ids:
            usados = CartonPartidaBingo.objects.filter(
                idpartida__in=partidas, idcarton__in=cartones_catalogo_ids).exists()
            if usados:
                messages.error(
                    request, "Oops. Un jugador más rápido compró uno de los cartones de catálogo que elegiste. Vuelve a intentarlo.")
                return redirect('venta_cartones')
            catalogo_validos = Carton.objects.filter(
                idcarton__in=cartones_catalogo_ids)
            cartones_a_asignar.extend(list(catalogo_validos))

        if cartones_generados:
            nuevos_cartones_db = [Carton(
                codigocarton=c_data['codigo'], matriznumeros=c_data['matriz'], esmaestro=False) for c_data in cartones_generados]
            Carton.objects.bulk_create(nuevos_cartones_db)
            codigos_creados = [c['codigo'] for c in cartones_generados]
            cartones_temporales = Carton.objects.filter(
                codigocarton__in=codigos_creados)
            cartones_a_asignar.extend(list(cartones_temporales))

        try:
            jugador.saldocreditojugador -= total_pagar
            jugador.save()

            nuevas_asignaciones = []
            for carton in cartones_a_asignar:
                for partida in partidas:
                    nuevas_asignaciones.append(CartonPartidaBingo(idjugador=jugador, idpartida=partida, idcarton=carton,
                                               preciopagado=precio_unitario, estadocarton='Vendido', fechacompra=datetime.now()))

            if nuevas_asignaciones:
                CartonPartidaBingo.objects.bulk_create(nuevas_asignaciones)

            # ==========================================
            # MAGIA 5: AVISAR A LA TIENDA EN TIEMPO REAL
            # ==========================================
            channel_layer = get_channel_layer()
            for carton in cartones_a_asignar:
                # El grupo de la tienda usa el ID del Bingo maestro
                async_to_sync(channel_layer.group_send)(
                    f'bingo_tienda_{bingo.idbingo}',
                    {
                        'type': 'evento_tienda',
                        'datos': {
                            'evento': 'carton_vendido',
                            'id_carton': carton.idcarton
                        }
                    }
                )
            # ==========================================

            messages.success(
                request, f"¡Adrenalina pura! Tus {cantidad_total_compra} cartones han sido registrados en la base de datos para el evento '{bingo.titulobingo}'.")
            return redirect('venta_cartones')

        except Exception as e:
            messages.error(
                request, f"Fallo crítico en la transacción: {str(e)}")
            return redirect('venta_cartones')

    bingos_disponibles = Bingo.objects.exclude(estadobingo__in=[
                                               'Finalizado', 'Cancelado']).filter(partidabingo__isnull=False).distinct()
    bingos_data = []
    for b in bingos_disponibles:
        partidas_bingo = PartidaBingo.objects.filter(idbingo=b)
        if not partidas_bingo.exists() or partidas_bingo.exclude(estadopartida='Programada').exists():
            continue

        comprados = CartonPartidaBingo.objects.filter(
            idjugador=jugador, idpartida__idbingo=b).values('idcarton').distinct().count()
        porcentaje_barra = min(int((comprados / 15) * 100), 100)
        usados_ids = CartonPartidaBingo.objects.filter(
            idpartida__idbingo=b).values_list('idcarton', flat=True)
        catalogo = Carton.objects.filter(
            esmaestro=True).exclude(idcarton__in=usados_ids)[:12]

        bingos_data.append({'bingo': b, 'comprados': comprados,
                           'porcentaje': porcentaje_barra, 'catalogo': catalogo})

    contexto = {'jugador': jugador, 'bingos_data': bingos_data}
    return render(request, 'negocio/venta_cartones.html', contexto)


@login_required
def mis_cartones(request):
    jugador = obtener_jugador_request(request)
    if not jugador:
        return redirect('registro_jugador')

    cartones_jugador = CartonPartidaBingo.objects.filter(idjugador=jugador).select_related(
        'idcarton', 'idpartida', 'idpartida__idbingo'
    ).order_by('-idpartida__idbingo__fechaprogramadabingo')

    bingos_dict = {}
    for c in cartones_jugador:
        if not getattr(c, 'idpartida', None) or not getattr(c.idpartida, 'idbingo', None):
            continue

        b_id = c.idpartida.idbingo.idbingo
        if b_id not in bingos_dict:
            bingos_dict[b_id] = {
                'bingo': c.idpartida.idbingo,
                'cartones_unicos': {}
            }

        carton = getattr(c, 'idcarton', None)
        if carton is None:
            continue

        carton_id = carton.idcarton
        if carton_id not in bingos_dict[b_id]['cartones_unicos']:
            bingos_dict[b_id]['cartones_unicos'][carton_id] = c

    bingos_agrupados = []
    for data in bingos_dict.values():
        bingos_agrupados.append({
            'bingo': data['bingo'],
            'cartones': list(data['cartones_unicos'].values())
        })

    context = {
        'bingos_agrupados': bingos_agrupados,
        'jugador': jugador
    }
    return render(request, 'cuenta/mis_cartones.html', context)


@login_required
def descargar_cartones_pdf(request, id_bingo):
    if request.method == 'POST':
        jugador = obtener_jugador_request(request)
        if not jugador:
            messages.error(request, "Perfil no encontrado.")
            return redirect('mis_cartones')

        cartones_ids = request.POST.getlist('cartones_seleccionados')
        if not cartones_ids:
            messages.warning(
                request, "No seleccionaste ningún cartón para imprimir.")
            return redirect('mis_cartones')

        bingo = get_object_or_404(Bingo, idbingo=id_bingo)
        cartones_asignados = CartonPartidaBingo.objects.filter(
            idjugador=jugador,
            idpartida__idbingo=bingo,
            idcarton__in=cartones_ids
        ).select_related('idcarton')

        cartones_unicos = {}
        for asig in cartones_asignados:
            carton = getattr(asig, 'idcarton', None)
            if carton is None:
                continue

            carton_id = carton.idcarton
            if carton_id in cartones_unicos:
                continue

            matriz = carton.matriznumeros
            if isinstance(matriz, str):
                try:
                    matriz = json.loads(matriz.replace("'", '"'))
                except Exception:
                    continue

            if isinstance(matriz, dict):
                try:
                    filas = []
                    for i in range(5):
                        filas.append(
                            [matriz['B'][i], matriz['I'][i], matriz['N'][i], matriz['G'][i], matriz['O'][i]])

                    cartones_unicos[carton_id] = {
                        'codigo': carton.codigocarton,
                        'filas': filas
                    }
                except Exception:
                    continue

        cartones_procesados = list(cartones_unicos.values())
        if not cartones_procesados:
            messages.warning(
                request, "No fue posible preparar los cartones para el PDF.")
            return redirect('mis_cartones')

        template = get_template('cuenta/cartones_pdf.html')
        context = {'bingo': bingo, 'jugador': jugador,
                   'cartones': cartones_procesados}
        html = template.render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="Mis_Cartones_{bingo.idbingo}_{jugador.aliasjugador}.pdf"'

        if pisa is None:
            return HttpResponse('La librería para generar PDFs no está disponible en este entorno.', status=500)

        pisa_status = pisa.CreatePDF(html, dest=response)

        if pisa_status.err:
            return HttpResponse('Tuvimos errores generando tu documento PDF', status=500)
        return response

    return redirect('mis_cartones')
