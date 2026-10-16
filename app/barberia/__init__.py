"""
EL PANEL DE GESTIÓN DE BARBERÍAS (BarberSaaS)
==============================================
Un producto más de la plataforma: caja, agenda, pagos a barberos, gastos
e inventario de una barbería con una o varias sedes. Vive en el mismo
despliegue y la misma base que el bot, y una barbería es un `client` más
(con `barberia_contratada`).

Lo que hay que leer antes de tocar esto:

  · `Instrucciones SAAS barberia.md` — las reglas de negocio.
  · `design_handoff_barbersaas/README.md` — cómo se ve y se comporta.
  · `docs/CONTINUAR_AQUI.md` — las trampas del proyecto, que aplican igual.

    modelos.py    las tablas `barb_*` (todas con `client_id` y RLS)
    permisos.py   qué rol ve qué sección, y la puerta del módulo contratado
    cuentas.py    entrar, el freno de intentos, la clave temporal y la
                  recuperación por correo
    paginas.py    el HTML (login, el armazón del panel, cuenta pausada)
    rutas.py      las rutas: /entrar, /b/…, /yo/…

Este `__init__` no importa nada a propósito: `database.py` carga
`modelos` al final de su propio módulo, y cualquier import de aquí
cerraría un círculo.
"""
