"""
NÚCLEO
======
Piezas transversales de las que dependen casi todos los demás módulos:

    database.py     Modelos, sesiones y migración del esquema
    message_log.py  Historial de mensajes que alimenta el panel
    ajustes.py      Lo que el dueño cambia desde el panel y persiste
    eventos.py      Reparte los mensajes nuevos a los paneles abiertos
    push.py         Avisos al celular con el panel cerrado
    media.py        Imágenes y notas de voz: bajar, subir y cachear
"""
