from datetime import date
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.core.validators import MinValueValidator , MaxValueValidator
from decimal import Decimal, InvalidOperation


# Create your models here.
class TipoSocio(models.Model):
    idtiposocio = models.AutoField(primary_key=True)
    nombretiposocio = models.CharField(
        max_length=100, 
        unique=True,
        null=True,
        blank=True,
        verbose_name="Nombre del Tipo de Socio"
    )
    roltiposocio = models.CharField(
        max_length=50, 
        unique=True,
        null=True,
        blank=True,
        verbose_name="Rol del Socio"
    )
    descripciondetiposocio = models.CharField(
        max_length=200, 
        null=True, 
        blank=True, 
        verbose_name="Descripción"
    )
    
    def __str__(self):
        return f"{self.nombretiposocio} ({self.roltiposocio})"



    class Meta:
        db_table = 'TipoSocio'
        verbose_name = 'Tipo de Socio'
        verbose_name_plural = 'Tipos de Socio'



def validarfechanacimiento(value):
    hoy = date.today()
    if value > hoy:
        raise ValidationError('La fecha de nacimiento no puede ser una fecha futura.')
    hace100anios = hoy.year - 100
    if value.year < hace100anios:
        raise ValidationError(f'La fecha de nacimiento es demasiado antigua (Límite: {hace100anios}).')
class Socio(models.Model):
    SEXO_CHOICES = [
        ('H', 'Hombre'),
        ('M', 'Mujer'),
    ]
    ESTADO_CHOICES = [
        ('Activo', 'Activo'),
        ('Inactivo', 'Inactivo'),
    ]
    idsocio = models.AutoField(primary_key=True)
    idtiposocio = models.ForeignKey(
        'TipoSocio', 
        on_delete=models.PROTECT, 
        db_column='idtiposocio',
        null=True,
        blank=True,
        verbose_name="Tipo de Socio"
    )
    primernombresocio = models.CharField(max_length=40, null=True, blank=True, verbose_name="Primer Nombre")
    segundonombresocio = models.CharField(max_length=40, null=True, blank=True, verbose_name="Segundo Nombre")
    primerapellidosocio = models.CharField(max_length=40, null=True, blank=True, verbose_name="Primer Apellido")
    segundoapellidosocio = models.CharField(max_length=40, null=True, blank=True, verbose_name="Segundo Apellido")
    cisocio = models.CharField(
        max_length=10, 
        unique=True,
        null=True,
        blank=True,
        verbose_name="Cédula de Identidad"
    )
    fechanacimientosocio = models.DateField(
        validators=[validarfechanacimiento],
        null=True,
        blank=True,
        verbose_name="Fecha de Nacimiento",
        help_text="El socio no puede ser mayor de 100 años ni haber nacido en el futuro."
    )
    telefonopersonalsocio = models.CharField(max_length=10, null=True, blank=True, verbose_name="Teléfono Personal")
    telefonotrabajosocio = models.CharField(max_length=25, null=True, blank=True, verbose_name="Teléfono Trabajo")
    direcciondomiciliosocio = models.CharField(max_length=255, null=True, blank=True, verbose_name="Dirección Domicilio")
    direcciontrabajosocio = models.CharField(max_length=255, null=True, blank=True, verbose_name="Dirección Trabajo")
    sexosocio = models.CharField(
        max_length=1, 
        choices=SEXO_CHOICES, 
        null=True, 
        blank=True, 
        verbose_name="Sexo"
    )
    estadosocio = models.CharField(
        max_length=10, 
        choices=ESTADO_CHOICES, 
        default='Activo', 
        verbose_name="Estado"
    )



    def __str__(self):
        return f"{self.primerapellidosocio} {self.primernombresocio} - {self.cisocio}"



    class Meta:
        db_table = 'Socio'
        verbose_name = 'Socio'
        verbose_name_plural = 'Socios'

class CuentaBancaria(models.Model):
    TIPO_CUENTA_CHOICES = [
        ('Ahorro', 'Ahorro'),
        ('Corriente', 'Corriente'),
    ]
    ESTADO_CUENTA_CHOICES = [
        ('Activo', 'Activo'),
        ('Inactivo', 'Inactivo'),
    ]
    idcuentabancaria = models.AutoField(primary_key=True)
    idsocio = models.ForeignKey(
        'Socio', 
        on_delete=models.PROTECT, 
        db_column='idsocio',
        verbose_name="Socio Titular"
    )   
    nombrebanco = models.CharField(max_length=100, verbose_name="Nombre del Banco")
    numerocuenta = models.CharField(max_length=30, unique=True, verbose_name="Número de Cuenta")    
    tipocuenta = models.CharField(
        max_length=20, 
        choices=TIPO_CUENTA_CHOICES, 
        verbose_name="Tipo de Cuenta"
    )  
    esprincipal = models.BooleanField(
        default=False, 
        verbose_name="¿Es cuenta principal?"
    )  
    fecharegistro = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Fecha de Registro"
    )
    estadocuenta = models.CharField(
        max_length=10, 
        choices=ESTADO_CUENTA_CHOICES, 
        default='Activo', 
        verbose_name="Estado de la Cuenta"
    )



    def clean(self):
        super().clean()
        if self._state.adding:
            cantidadcuentas = CuentaBancaria.objects.filter(idsocio=self.idsocio).count()
            if cantidadcuentas >= 2:
                raise ValidationError(
                    "Bloqueo de seguridad: El socio ya tiene el límite máximo de 2 cuentas bancarias registradas."
                )
    
    def __str__(self):
        return f"{self.nombrebanco} - {self.numerocuenta} (Socio ID: {self.idsocio_id})"



    class Meta:
        db_table = 'CuentaBancaria'
        verbose_name = 'Cuenta Bancaria'
        verbose_name_plural = 'Cuentas Bancarias'
        constraints = [
            models.UniqueConstraint(
                fields=['idsocio'], 
                condition=Q(esprincipal=True), 
                name='uq_cuentabancaria_esprincipal_por_socio'
            )
        ]
class MetodoPago(models.Model):
    ESTADO_METODO_CHOICES = [
        ('Activo', 'Activo'),
        ('Inactivo', 'Inactivo'),
    ]
    idmetodopago = models.AutoField(primary_key=True)
    nombremetodopago = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Nombre del Método de Pago"
    )   
    descripcionmetodopago = models.CharField(
        max_length=200, 
        null=True, 
        blank=True, 
        verbose_name="Descripción del Método"
    )    
    estadometodopago = models.CharField(
        max_length=20, 
        choices=ESTADO_METODO_CHOICES, 
        default='Activo', 
        verbose_name="Estado del Método"
    )    
    urlmetodopago = models.CharField(
        max_length=255, 
        verbose_name="URL o Enlace del Método"
    )



    def __str__(self):
        return f"{self.nombremetodopago} ({self.estadometodopago})"



    class Meta:
        db_table = 'MetodoPago'
        verbose_name = 'Método de Pago'
        verbose_name_plural = 'Métodos de Pago'
class Prestamo(models.Model):
    ESTADO_PRESTAMO_CHOICES = [
        ('Solicitado', 'Solicitado'),
        ('Aprobado', 'Aprobado'),
        ('En espera', 'En espera'),
        ('Liquidado', 'Liquidado'),
    ]
    idprestamo = models.AutoField(primary_key=True)    
    idsocio = models.ForeignKey(
        'Socio', 
        on_delete=models.PROTECT, 
        db_column='idsocio',
        null=True,
        blank=True,
        verbose_name="Socio Solicitante"
    )
    montoprestamosolicitado = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))], 
        verbose_name="Monto Solicitado"
    )    
    tasainteres = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00'),
        verbose_name="Tasa de Interés (%)"
    )    
    montototalpagar = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Monto Total a Pagar"
    )    
    saldopendiente = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Saldo Pendiente"
    ) 
    numerocuotas = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Número de Cuotas"
    )    
    fechasolicitud = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de Solicitud"
    )
    fechavencimiento = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de Vencimiento"
    )    
    estadoprestamo = models.CharField(
        max_length=20, 
        choices=ESTADO_PRESTAMO_CHOICES, 
        default='Solicitado', # Por lógica, todo préstamo inicia como solicitado
        verbose_name="Estado del Préstamo"
    )



    def __str__(self):
        return f"Préstamo #{self.idprestamo} - Socio ID: {self.idsocio_id} - {self.estadoprestamo}"



    class Meta:
        db_table = 'Prestamo'
        verbose_name = 'Préstamo'
        verbose_name_plural = 'Préstamos'
class Pago(models.Model):
    ESTADO_PAGO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Validado', 'Validado'),
        ('Rechazado', 'Rechazado'),
    ]
    idpago = models.AutoField(primary_key=True) 
    idprestamo = models.ForeignKey(
        'Prestamo', 
        on_delete=models.PROTECT, 
        db_column='idprestamo',
        verbose_name="Préstamo"
    )
    idmetodopago = models.ForeignKey(
        'MetodoPago', 
        on_delete=models.PROTECT, 
        db_column='idmetodopago',
        verbose_name="Método de Pago"
    )
    montopagado = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Monto Pagado"
    )
    numeroreferencia = models.CharField(
        max_length=50, 
        unique=True, 
        null=True, 
        blank=True, 
        verbose_name="Número de Referencia"
    )
    fechapago = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Fecha de Registro del Pago"
    )
    fechaconfirmacionadmin = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fecha Confirmación Admin"
    )
    comprobantepago = models.FileField(
        upload_to='pago/comprobantes_pagos/', 
        max_length=255, 
        null=False, 
        blank=False, 
        verbose_name="Archivo del Comprobante"
    )
    estadopago = models.CharField(
        max_length=20, 
        choices=ESTADO_PAGO_CHOICES, 
        default='Pendiente', 
        verbose_name="Estado del Pago"
    )



    def __str__(self):
        return f"Pago {self.idpago} - {self.idprestamo.idsocio} (${self.montopagado})"



    class Meta:
        db_table = 'Pago'
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
class Bingo(models.Model):
    TIPO_BINGO_CHOICES = [
        ('Virtual', 'Virtual'),
        ('Presencial', 'Presencial'),
    ]
    ESTADO_BINGO_CHOICES = [
        ('Programado', 'Programado'),
        ('En Curso', 'En Curso'),
        ('Finalizado', 'Finalizado'),
        ('Cancelado', 'Cancelado'),
    ]
    idbingo = models.AutoField(primary_key=True)
    titulobingo = models.CharField(
        max_length=150, 
        verbose_name="Título del Bingo"
    )
    fechaprogramadabingo = models.DateTimeField(
        verbose_name="Fecha y Hora del Evento"
    )
    tipobingo = models.CharField(
        max_length=20, 
        choices=TIPO_BINGO_CHOICES,
        verbose_name="Tipo de Bingo"
    )
    lugarbingo = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        verbose_name="Lugar (si es presencial)"
    )
    urlsesionbingo = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        verbose_name="Link de la sesión (si es virtual)"
    )
    preciocarton = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Precio del Cartón"
    )
    premiomayor = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        verbose_name="Monto del Premio Mayor"
    )
    descripcionpremiomayor = models.CharField(
        max_length=100, 
        verbose_name="¿Qué es el premio mayor?"
    )
    estadobingo = models.CharField(
        max_length=20, 
        choices=ESTADO_BINGO_CHOICES, 
        default='Programado',
        verbose_name="Estado del Bingo"
    )
    rutaimagenpremiomayor = models.ImageField(
        upload_to='bingo/imagen_premio_mayor/', 
        max_length=300, 
        null=True, 
        blank=True,
        verbose_name="Imagen del Premio"
    )
    urlvideopromocional = models.FileField(
        upload_to='bingo/video_promocional/', 
        max_length=300, 
        null=True, 
        blank=True,
        verbose_name="Video Promocional"
    )
    descripcionpremios = models.TextField(
        max_length=500, 
        null=True, 
        blank=True, 
        verbose_name="Descripción de otros premios"
    )
    idunidadmonetaria = models.ForeignKey(
        'UnidadMonetaria',
        on_delete=models.PROTECT,
        db_column='idunidadmonetaria',
        null=True,
        blank=True,
        verbose_name='Unidad Monetaria'
    )


    def __str__(self):
        return f"{self.titulobingo} ({self.fechaprogramadabingo.date()})"



    class Meta:
        db_table = 'Bingo'
        verbose_name = 'Bingo'
        verbose_name_plural = 'Bingos'
class Ahorro(models.Model):
    TIPO_AHORRO_CHOICES = [
        ('Obligatorio', 'Obligatorio'),
        ('Voluntario', 'Voluntario'),
    ]
    ESTADO_AHORRO_CHOICES = [
        ('Activo', 'Activo'),
        ('Inactivo', 'Inactivo'),
    ]
    idahorro = models.AutoField(primary_key=True)
    idsocio = models.ForeignKey(
        'Socio', 
        on_delete=models.PROTECT, 
        db_column='idsocio',
        verbose_name="Socio"
    )
    idbingo = models.ForeignKey(
        'Bingo', 
        on_delete=models.PROTECT, 
        db_column='idbingo',
        verbose_name="Bingo Asociado"
    )
    tipoahorro = models.CharField(
        max_length=50, 
        choices=TIPO_AHORRO_CHOICES, 
        verbose_name="Tipo de Ahorro"
    )
    montoahorro = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Monto Ahorrado"
    )
    fechaahorro = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de Ahorro"
    )
    comentarioahorro = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        verbose_name="Comentario"
    )
    estadoahorro = models.CharField(
        max_length=25, 
        choices=ESTADO_AHORRO_CHOICES, 
        verbose_name="Estado del Ahorro"
    )



    def __str__(self):
        return f"Ahorro #{self.idahorro} - Socio {self.idsocio_id} (${self.montoahorro})"



    class Meta:
        db_table = 'Ahorro'
        verbose_name = 'Ahorro'
        verbose_name_plural = 'Ahorros'
class Jugador(models.Model):
    ESTADO_CUENTA_CHOICES = [
        ('Activo', 'Activo'),
        ('Suspendido', 'Suspendido'),
        ('Moroso', 'Moroso'),
    ]
    idjugador = models.AutoField(primary_key=True)
    idsocio = models.ForeignKey(
        'Socio', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        db_column='idsocio',
        verbose_name="Socio Vinculado"
    )
    idsocio = models.ForeignKey(
        'Socio', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        db_column='idsocio',
        verbose_name="Socio Vinculado"
    )
    nombresjugador = models.CharField(
        max_length=150, 
        null=True, 
        blank=True, 
        verbose_name="Nombres Completos"
    )
    
    apellidosjugador = models.CharField(
        max_length=150, 
        null=True, 
        blank=True, 
        verbose_name="Apellidos Completos"
    )
    
    cedulaidentidadjugador = models.CharField(
        max_length=20, 
        unique=True, 
        null=True, 
        blank=True, 
        verbose_name="Cédula de Identidad"
    )
    avatarjugador = models.ImageField(
        upload_to='jugador/avatar/', 
        null=True, 
        blank=True, 
        verbose_name="Avatar/Foto"
    )  
    aliasjugador = models.CharField(
        max_length=100, 
        unique=True, 
        null=True, 
        blank=True, 
        verbose_name="Alias en el Juego"
    )
    correojugador = models.EmailField(
        max_length=200, 
        unique=True, 
        null=True, 
        blank=True, 
        verbose_name="Correo Electrónico"
    )   
    fecharegistrojugador = models.DateTimeField(
        auto_now_add=True, 
        null=True,
        blank=True,
        verbose_name="Fecha de Registro"
    )
    saldocreditojugador = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Saldo/Crédito"
    )
    estadocuentajugador = models.CharField(
        max_length=20, 
        choices=ESTADO_CUENTA_CHOICES, 
        default='Activo',
        verbose_name="Estado de Cuenta"
    )



    def clean(self):
        super().clean()
        if not self.idsocio:
            errores = {}
            if not self.nombresjugador:
                errores['nombresjugador'] = "Los nombres son obligatorios para jugadores externos."
            if not self.apellidosjugador:
                errores['apellidosjugador'] = "Los apellidos son obligatorios para jugadores externos."
            if not self.cedulaidentidadjugador:
                errores['cedulaidentidadjugador'] = "La cédula es obligatoria para verificar la identidad."
            if not self.correojugador:
                errores['correojugador'] = "El correo es obligatorio para contactar al jugador."
            if errores:
                raise ValidationError(errores)



    def __str__(self):
        if self.nombresjugador and self.apellidosjugador:
            return f"{self.nombresjugador} {self.apellidosjugador} ({self.aliasjugador})"
        return self.aliasjugador or f"Jugador {self.idjugador}"



    class Meta:
        db_table = 'Jugador'
        verbose_name = 'Jugador'
        verbose_name_plural = 'Jugadores'
class PartidaBingo(models.Model):
    ESTADO_PARTIDA_CHOICES = [
        ('Programada', 'Programada'),
        ('En Juego', 'En Juego'),
        ('Verificando', 'Verificando'),
        ('Desempate', 'Desempate'),
        ('Finalizada', 'Finalizada'),
    ]
    idpartidabingo = models.AutoField(primary_key=True)
    idbingo = models.ForeignKey(
        'Bingo', 
        on_delete=models.PROTECT, 
        db_column='idbingo',
        verbose_name="Evento de Bingo"
    )
    idjugadororganador = models.ForeignKey(
        'Jugador', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        db_column='idjugadororganador',
        verbose_name="Jugador Organizador / Ganador"
    )
    nombreronda = models.CharField(
        max_length=100, 
        verbose_name="Nombre de la Ronda"
    )
    valorefectivo = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Premio en Efectivo"
    )
    valorpremio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Premio en Efectivo (Alias)"
    )
    premiomaterial = models.CharField(
        max_length=150, 
        verbose_name="Premio Material"
    )
    estadopartida = models.CharField(
        max_length=20, 
        choices=ESTADO_PARTIDA_CHOICES, 
        default='Programada',
        verbose_name="Estado de la Partida"
    )
    bolascantadas = models.TextField(
        default='',
        verbose_name="Historial de Bolas Cantadas"
    )
    ultimabola = models.IntegerField(
        default=0,
        verbose_name="Última Bola Cantada"
    )
    haydesempate = models.BooleanField(
        null=True, 
        blank=True, 
        verbose_name="¿Hubo Desempate?"
    )
    # varchar(max) para guardar múltiples IDs separados por comas
    idbingadores = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="IDs de los Ganadores"
    )   
    bolamayordesempate = models.IntegerField(
        null=True, 
        blank=True, 
        verbose_name="Bola Mayor (Desempate)"
    )   
    horainicio = models.DateTimeField(
        verbose_name="Hora de Inicio"
    )
    horainiciopartida = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Hora de Inicio de la Partida"
    )
    modalidad_victoria = models.CharField(
        max_length=50,
        default='Tabla Llena',
        verbose_name="Modalidad de Victoria"
    )
    estadopremiomaterial = models.CharField(
        max_length=20,
        default='Ninguno',
        verbose_name="Estado del Premio Material"
    )
    sorteodesempate = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name="Sorteo de Desempate"
    )
    horafin = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Hora de Finalización"
    )



    @property
    def valorpremio_alias(self):
        return self.valorpremio

    @valorpremio_alias.setter
    def valorpremio_alias(self, value):
        self.valorpremio = value

    @property
    def valorpremio(self):
        if self.valorefectivo is not None:
            try:
                return Decimal(self.valorefectivo)
            except (TypeError, ValueError, InvalidOperation):
                return self.valorefectivo
        if hasattr(self, '_valorpremio') and self._valorpremio is not None:
            try:
                return Decimal(self._valorpremio)
            except (TypeError, ValueError, InvalidOperation):
                return self._valorpremio
        return Decimal('0.00')

    @valorpremio.setter
    def valorpremio(self, value):
        try:
            self.valorefectivo = Decimal(value)
        except (TypeError, ValueError, InvalidOperation):
            self.valorefectivo = value
        try:
            self._valorpremio = Decimal(value)
        except (TypeError, ValueError, InvalidOperation):
            self._valorpremio = value

    @property
    def horainiciopartida_alias(self):
        return self.horainiciopartida or self.horainicio

    @horainiciopartida_alias.setter
    def horainiciopartida_alias(self, value):
        self.horainiciopartida = value

    def __str__(self):
        return f"{self.nombreronda} - Bingo {self.idbingo_id} ({self.estadopartida})"



    class Meta:
        db_table = 'PartidaBingo'
        verbose_name = 'Partida de Bingo'
        verbose_name_plural = 'Partidas de Bingo'
class Carton(models.Model):
    idcarton = models.AutoField(
        primary_key=True, 
        verbose_name="ID Interno del Cartón"
    )  
    codigocarton = models.CharField(
        max_length=30, 
        unique=True, 
        verbose_name="Código/Serial del Cartón"
    )
    matriznumeros = models.JSONField(
        verbose_name="Matriz de Números (Formato JSON)"
    )
    esmaestro = models.BooleanField(
        default=False,
        verbose_name="¿Es Cartón Maestro?"
    )
    indicevictoria = models.IntegerField(
        default=0,
        validators=[
        MinValueValidator(0),
        MaxValueValidator(100)
        ],
        verbose_name="Índice de Victoria Estimado"
    )



    def __str__(self):
        tipo = "Maestro" if self.esmaestro else "Temporal"
        return f"{self.codigocarton} - {tipo}"



    class Meta:
        db_table = 'Carton'
        verbose_name = 'Catálogo de Cartón'
        verbose_name_plural = 'Catálogo de Cartones'
class CartonPartidaBingo(models.Model):
    ESTADO_CARTON_CHOICES = [
        ('Disponible', 'Disponible'),
        ('Reservado', 'Reservado'),
        ('Vendido', 'Vendido'),
        ('Anulado', 'Anulado'),
    ]
    idcartonpartida = models.AutoField(primary_key=True)
    idjugador = models.ForeignKey(
        'Jugador', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        db_column='idjugador'
    )
    idpartida = models.ForeignKey(
        'PartidaBingo', 
        on_delete=models.CASCADE, 
        db_column='idpartida'
    )
    idcarton = models.ForeignKey(
        'Carton', 
        on_delete=models.PROTECT, 
        db_column='idcarton'
    )
    preciopagado = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    fechacompra = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name="Fecha y Hora de Adquisición"
    )
    estadocarton = models.CharField(
        max_length=20, 
        choices=ESTADO_CARTON_CHOICES, 
        default='Disponible'
    )
    esganador = models.BooleanField(default=False)
    cantidadaciertos = models.IntegerField(default=0)
    fechaganador = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name="Momento del Triunfo"
    )



    class Meta:
        db_table = 'CartonPartidaBingo'
        verbose_name = 'Cartón en Juego'
        verbose_name_plural = 'Control de Cartones por Partida'
        constraints = [
            models.UniqueConstraint(
                fields=['idcarton', 'idpartida'], 
                name='uq_cartonpartidabingo_idscompuestos'
            )
        ]



    def __str__(self):
        return f"Partida {self.idpartida_id} - {self.idcarton.codigocarton}"
class PlataformaJuego(models.Model):
    idplataformajuego = models.AutoField(
        primary_key=True, 
        verbose_name="ID de la Plataforma"
    )
    nombreplataforma = models.CharField(
        max_length=25, 
        unique=True, 
        verbose_name="Nombre de la Plataforma"
    )
    logoplataforma = models.ImageField(
        upload_to='plataforma/logos/', 
        null=True, 
        blank=True, 
        verbose_name="Logo de la Plataforma"
    )
    urlplataforma = models.URLField(
        max_length=255, 
        verbose_name="URL de Acceso"
    )
    descripcionplataforma = models.CharField(
        max_length=200, 
        null=True, 
        blank=True, 
        verbose_name="Descripción"
    )
    estadoplataforma = models.BooleanField(
        default=True, 
        verbose_name="Estado Activo"
    )
    fechaadquisicionlicencia = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="Fecha de Adquisición"
    )
    fechavencimientolicencia = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="Fecha de Vencimiento"
    )
    contactoplataforma = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        verbose_name="Contacto del Proveedor"
    )



    def __str__(self):
        return self.nombreplataforma



    class Meta:
        db_table = 'PlataformaJuego'
        verbose_name = 'Plataforma de Juego'
        verbose_name_plural = 'Plataformas de Juego'
class SesionJuego(models.Model):
    ESTADO_SESION_CHOICES = [
        ('Activa', 'Activa'),
        ('Finalizada', 'Finalizada'),
        ('Caida', 'Caída'),
    ]
    idsesion = models.AutoField(
        primary_key=True, 
        verbose_name="ID de Sesión"
    )
    idplataforma = models.ForeignKey(
        'PlataformaJuego', 
        on_delete=models.CASCADE, 
        db_column='idplataforma',
        verbose_name="Plataforma"
    )
    idjugador = models.ForeignKey(
        'Jugador', 
        on_delete=models.CASCADE, 
        db_column='idjugador',
        verbose_name="Jugador"
    )
    idpartida = models.ForeignKey(
        'PartidaBingo', 
        on_delete=models.CASCADE, 
        db_column='idpartida',
        verbose_name="Partida"
    )
    fechainiciosesion = models.DateTimeField(
        verbose_name="Inicio de Sesión"
    )
    fechafinsesion = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fin de Sesión"
    )
    ipconexion = models.GenericIPAddressField(
        null=True, 
        blank=True, 
        verbose_name="Dirección IP"
    )
    dispositivoconexion = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        verbose_name="Dispositivo"
    )
    estadosesion = models.CharField(
        max_length=15, 
        choices=ESTADO_SESION_CHOICES, 
        verbose_name="Estado"
    )
    latenciaping = models.IntegerField(
        null=True, 
        blank=True, 
        verbose_name="Latencia (ms)"
    )
    navegadorweb = models.CharField(
        max_length=150, 
        null=True, 
        blank=True, 
        verbose_name="Navegador"
    )
    tokenconexion = models.CharField(
        max_length=255, 
        unique=True, 
        verbose_name="Token de Conexión"
    )
    motivocierre = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        verbose_name="Motivo de Cierre"
    )



    def __str__(self):
        return f"Sesión {self.idsesion} - Jugador: {self.idjugador_id}"



    class Meta:
        db_table = 'SesionJuego'
        verbose_name = 'Sesión de Juego'
        verbose_name_plural = 'Sesiones de Juego'
        
        constraints = [
            models.CheckConstraint(
                check=models.Q(estadosesion__in=['Activa', 'Finalizada', 'Caida']),
                name='chk_sesionjuego_estadosesion'
            )
        ]
class Regalo(models.Model):
    ESTADO_REGALO_CHOICES = [
        ('Acumulado', 'Acumulado'),
        ('Sorteado', 'Sorteado'),
        ('Entregado', 'Entregado'),
    ]
    idregalo = models.AutoField(
        primary_key=True, 
        verbose_name="ID de Regalo"
    )
    nombreregalo = models.CharField(
        max_length=100, 
        verbose_name="Nombre/Tipo de Regalo"
    )
    descripcionregalo = models.CharField(
        max_length=200, 
        null=True, 
        blank=True, 
        verbose_name="Descripción o Mensaje"
    )
    valorregalo = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Valor del Regalo ($)"
    )
    fechaentregaregalo = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fecha de Entrega"
    )
    estadoregalo = models.CharField(
        max_length=20, 
        choices=ESTADO_REGALO_CHOICES, 
        verbose_name="Estado del Regalo"
    )
    fechaultimaactualizacion = models.DateTimeField(
        auto_now=True, 
        verbose_name="Última Actualización"
    )
    urlimagen = models.ImageField(
        upload_to='regalo/imagenes/', 
        verbose_name="Imagen del Regalo"
    )



    def __str__(self):
        return f"{self.nombreregalo} - {self.estadoregalo}"



    class Meta:
        db_table = 'Regalo'
        verbose_name = 'Regalo/Premio'
        verbose_name_plural = 'Catálogo de Regalos'
        constraints = [
            models.CheckConstraint(
                check=models.Q(estadoregalo__in=['Acumulado', 'Sorteado', 'Entregado']),
                name='chk_regalo_estadoregalo'
            )
        ]
class AporteSemanal(models.Model):
    ESTADO_APORTE_CHOICES = [
        ('Al Dia', 'Al Día'),
        ('Atrasado', 'Atrasado'),
    ]
    METODO_INGRESO_CHOICES = [
        ('Efectivo', 'Efectivo'),
        ('Transferencia', 'Transferencia'),
        ('Fisico', 'Físico'),
    ]
    idaporte = models.AutoField(
        primary_key=True, 
        verbose_name="ID de Aporte"
    )
    idsocio = models.ForeignKey(
        'Socio', 
        on_delete=models.CASCADE, 
        db_column='idsocio',
        verbose_name="Socio"
    )
    idregalo = models.ForeignKey(
        'Regalo', 
        on_delete=models.CASCADE, 
        db_column='idregalo',
        verbose_name="Regalo Asignado"
    )
    idpartida = models.ForeignKey(
        'PartidaBingo', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        db_column='idpartida',
        verbose_name="Partida Asociada"
    )
    numerosemana = models.IntegerField(
        null=True, 
        blank=True, 
        verbose_name="Número de Semana"
    )
    fechaplanificadadada = models.DateTimeField(
        verbose_name="Fecha Planificada"
    )
    fechaentregareal = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fecha de Entrega Real"
    )
    metodoingreso = models.CharField(
        max_length=50, 
        choices=METODO_INGRESO_CHOICES,
        verbose_name="Método de Ingreso"
    )
    referenciaingreso = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        verbose_name="Referencia/Comprobante"
    )
    estadoaporte = models.CharField(
        max_length=20, 
        choices=ESTADO_APORTE_CHOICES,
        null=True, 
        blank=True,
        verbose_name="Estado del Aporte"
    )



    def __str__(self):
        return f"Aporte {self.idaporte} - Socio: {self.idsocio_id} - Semana: {self.numerosemana}"



    class Meta:
        db_table = 'AporteSemanal'
        verbose_name = 'Aporte Semanal'
        verbose_name_plural = 'Control de Aportes Semanales'
        constraints = [
            models.CheckConstraint(
                check=models.Q(estadoaporte__in=['Al Dia', 'Atrasado']),
                name='chk_aportesemanal_estadoaporte'
            ),
            models.CheckConstraint(
                check=models.Q(metodoingreso__in=['Efectivo', 'Transferencia', 'Fisico']),
                name='chk_aportesemanal_metodoingreso'
            )
        ]

class UnidadMonetaria(models.Model):
    idunidad = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=50, unique=True)
    simbolo = models.CharField(max_length=10, null=True, blank=True)

    @property
    def nombremoneda(self):
        return self.nombre

    @nombremoneda.setter
    def nombremoneda(self, value):
        self.nombre = value

    @property
    def simbolomoneda(self):
        return self.simbolo or ''

    @simbolomoneda.setter
    def simbolomoneda(self, value):
        self.simbolo = value

    @property
    def tipomoneda(self):
        return getattr(self, '_tipomoneda', 'Efectivo')

    @tipomoneda.setter
    def tipomoneda(self, value):
        self._tipomoneda = value

    @property
    def tasaconversionmoneda(self):
        return getattr(self, '_tasaconversionmoneda', Decimal('1.00'))

    @tasaconversionmoneda.setter
    def tasaconversionmoneda(self, value):
        self._tasaconversionmoneda = value

    @property
    def estadomoneda(self):
        return getattr(self, '_estadomoneda', True)

    @estadomoneda.setter
    def estadomoneda(self, value):
        self._estadomoneda = value

    def __str__(self):
        return f"{self.nombre} ({self.simbolo})" if self.simbolo else self.nombre

    class Meta:
        db_table = 'UnidadMonetaria'
        verbose_name = 'Unidad Monetaria'
        verbose_name_plural = 'Unidades Monetarias'


class ConfiguracionWeb(models.Model):
    idconfig = models.AutoField(primary_key=True)
    clave = models.CharField(max_length=100, unique=True)
    valor = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.clave}"

    class Meta:
        db_table = 'ConfiguracionWeb'
        verbose_name = 'Configuración Web'
        verbose_name_plural = 'Configuraciones Web'


class MensajeChat(models.Model):
    idmensaje = models.AutoField(primary_key=True)
    idbingo = models.ForeignKey('Bingo', on_delete=models.CASCADE, db_column='idbingo')
    usuario = models.CharField(max_length=200)
    mensaje = models.TextField()
    fechahora = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario}: {self.mensaje[:40]}"

    class Meta:
        db_table = 'MensajeChat'
        verbose_name = 'Mensaje de Chat'
        verbose_name_plural = 'Mensajes de Chat'



















































