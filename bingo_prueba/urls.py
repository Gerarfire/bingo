"""
URL configuration for bingo_prueba project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""

from django.contrib import admin
from django.urls import path
from bingo import views


urlpatterns = [
    path('admin/', admin.site.urls),
    # Minimal routes to allow runserver while refactoring views
    path('', views.inicio, name='inicio'),
    path('como-jugar/', views.como_jugar, name='como_jugar'),
    path('login/', views.inicio_sesion, name='login'),
    path('logout/', views.cerrar_sesion, name='logout'),
    path('perfil/', views.perfil, name='perfil'),
    path('seleccion-registro/', views.seleccion_registro,
         name='seleccion_registro'),
    path('registro-socio/', views.registro_socio, name='registro_socio'),
    path('registro-jugador/', views.registro_jugador, name='registro_jugador'),
    path('mis-cartones/', views.mis_cartones, name='mis_cartones'),
    path('mis-cartones/<int:id_bingo>/pdf/',
         views.descargar_cartones_pdf, name='descargar_cartones_pdf'),
    path('venta-cartones/', views.venta_cartones, name='venta_cartones'),
    path('bingo/', views.bingo_publico, name='bingo'),
    path('bingo-publico/', views.bingo_publico, name='bingo_publico'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard-admin/', views.dashboard, name='dashboard_admin'),
    path('finanzas/', views.finanzas, name='finanzas'),
    path('creditos/', views.creditos, name='creditos'),
    path('partidas/', views.partidas, name='partidas'),
    path('sala-espera/<int:id_partida>/',
         views.sala_espera, name='sala_espera'),
    path('reportes/socios-puntuales/', views.reporte_socios_puntuales,
         name='reporte_socios_puntuales'),
    path('reportes/liquidacion-bingo/<int:id_bingo>/',
         views.reporte_liquidacion_bingo, name='reporte_liquidacion_bingo'),
    path('reportes/cartera-prestamos/', views.reporte_cartera_prestamos,
         name='reporte_cartera_prestamos'),
    path('reportes/caja-semanal-pdf/', views.reporte_caja_semanal_pdf,
         name='reporte_caja_semanal_pdf'),

    # ==========================================
    # PARTIDA (El Motor del Juego en Vivo)
    # ==========================================
    # Vistas del Jugador
    path('juego/sala-espera/<int:id_partida>/',
         views.sala_espera, name='sala_espera_partida'),
    path('juego/sala-espera/desempate/<int:id_partida>/',
         views.sala_espera_desempate, name='sala_espera_desempate'),
    path('juego/tablero-en-vivo/<int:id_partida>/',
         views.tablero_tiempo_real, name='tablero_tiempo_real'),
    path('juego/sesion/<int:id_partida>/',
         views.sesion_juego, name='sesion_juego'),

    # Vistas del Administrador / Operador del Bingo
    path('juego/partida/<int:id_partida>/estado-json/',
         views.estado_partida_json, name='estado_partida_json'),
    path('juego/admin/tablero/<int:id_partida>/',
         views.tablero_admin, name='tablero_admin'),
    path('juego/admin/desempate/<int:id_partida>/',
         views.desempate_admin, name='desempate_admin'),
    path('juego/admin/consola/<int:id_partida>/',
         views.consola_juego, name='consola_juego'),

    # Lógica de las bolas
    path('api/partida/<int:id_partida>/sacar_bola/',
         views.sacar_bola_api, name='sacar_bola_api'),

    # ==========================================
    # COMPRA DE CARTONES
    # ==========================================
    path('juego/comprar-cartones/<int:id_partida>/',
         views.ventana_cartones, name='ventana_cartones'),
    path('api/partida/<int:id_partida>/comprar-cartones/',
         views.compra_carton_api, name='compra_carton_api'),

    # ==========================================
    # RECARGA DE SALDO
    # ==========================================
    path('recargar-saldo/', views.recargar_saldo, name='recargar_saldo'),
    path('api/recargar-saldo/', views.procesar_recarga_saldo,
         name='procesar_recarga_saldo'),
]
