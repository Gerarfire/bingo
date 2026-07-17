
from django.contrib import admin
from .models import TipoSocio, Socio, Prestamo, Pago, MetodoPago, Regalo
from .models import AporteSemanal, CuentaBancaria, Ahorro, Bingo, PartidaBingo
from .models import CartonPartidaBingo, Carton, Jugador, SesionJuego, PlataformaJuego


# Register your models here.
admin.site.register(TipoSocio)
admin.site.register(Socio)
admin.site.register(Prestamo)
admin.site.register(Pago)
admin.site.register(MetodoPago)
admin.site.register(Regalo)
admin.site.register(AporteSemanal)
admin.site.register(CuentaBancaria)
admin.site.register(Ahorro)
admin.site.register(Bingo)
admin.site.register(PartidaBingo)
admin.site.register(CartonPartidaBingo)
admin.site.register(Carton)
admin.site.register(Jugador)
admin.site.register(SesionJuego)
admin.site.register(PlataformaJuego)
