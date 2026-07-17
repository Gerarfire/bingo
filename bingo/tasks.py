
from celery import shared_task
from .models import Carton
from .services import generar_lote_cartones



@shared_task
def fabricar_cartones_maestros_task(cantidad):
    """
    Tarea asíncrona: Fabrica miles de cartones en segundo plano sin congelar la web.
    """
    try:
        # Generamos la lista de diccionarios con el motor RNG
        lote = generar_lote_cartones(cantidad)
        
        # Preparamos los objetos para la base de datos
        cartones_db = [
            Carton(
                codigocarton=c['codigo'], 
                matriznumeros=c['matriz'], 
                esmaestro=True
            ) for c in lote
        ]
        
        # Inserción masiva ultra rápida
        Carton.objects.bulk_create(cartones_db)
        
        return f"Éxito: Se estamparon {cantidad} cartones maestros."
    except Exception as e:
        return f"Error en fábrica: {str(e)}"

