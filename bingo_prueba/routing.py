from django.urls import re_path
from bingo import consumers 



websocket_urlpatterns = [
    # Captura el ID de la partida directamente desde la URL del WebSocket
    re_path(r'ws/juego/(?P<id_partida>\w+)/$', consumers.BingoConsumer.as_asgi()),
]
