"""
CUÁNTA IA GASTÓ CADA NEGOCIO
=============================
El medidor del paquete de IA. Es lo que convierte "la IA está activada" en
algo que se puede facturar y, sobre todo, en algo que se puede **acotar**.

    Una fila por cliente y mes, que se va sumando.

No una fila por llamada: con un `UPDATE ... SET mensajes = mensajes + 1`
basta para facturar y para frenar, y no crece una tabla de registro que
después hay que limpiar. Si algún día hace falta el detalle por día, se
agrega una columna más, no un histórico.

LOS TOKENS SON LOS DE VERDAD
----------------------------
Salen de `usage_metadata`, que es lo que Gemini responde junto con el
texto. No se estiman por longitud del prompt: facturar sobre una
estimación es facturar sobre una suposición, y la diferencia la paga
siempre el mismo.

EL TOPE NO ROMPE NADA
---------------------
Al pasarse del tope mensual, `interpretar()` devuelve `NO_SE` y el bot
sigue vendiendo con el menú de siempre — el mismo camino que ya recorre
cuando Gemini da timeout o se queda sin cuota. Un cliente que se pasa no
se queda sin bot: se queda sin el extra.

Por eso el tope se puede poner generoso sin miedo. Lo que protege es el
margen: el peor caso de un cliente deja de ser "lo que decida gastar" y
pasa a ser un número que tú elegiste.
"""

from sqlalchemy import func

from app import config
from app.core.database import IAUso, ahora_utc, get_session


def periodo_actual() -> str:
    """
    El mes en curso, "2026-08".

    En UTC, igual que el tope diario por contacto (`gemini._supera_el_tope`).
    Que el corte de mes de la factura caiga a medianoche UTC y no a la hora
    local de cada negocio es exactamente lo que se quiere: si dependiera de
    la zona del cliente, dos clientes cerrarían el mes en momentos
    distintos y el consumo total no cuadraría con nada.
    """
    return ahora_utc().strftime("%Y-%m")


def _fila(session, client_id: int, periodo: str, crear=False):
    fila = (session.query(IAUso)
            .filter_by(client_id=client_id, periodo=periodo).first())
    if fila is None and crear:
        fila = IAUso(client_id=client_id, periodo=periodo,
                     mensajes=0, tokens_in=0, tokens_out=0)
        session.add(fila)
    return fila


def _inquilino() -> int | None:
    from app.core import tenencia
    return tenencia.actual_o_none()


def anotar(tokens_in: int = 0, tokens_out: int = 0, client_id: int = None):
    """
    Suma un mensaje interpretado al contador de este mes.

    Se llama UNA vez por respuesta de la IA que llegó de verdad. Los
    intentos que fallan no se anotan: no consumieron nada que se pueda
    facturar, y contarlos convertiría una clave mal puesta en consumo del
    cliente.

    Nunca levanta. Perder una anotación es un céntimo mal contado; tumbar
    la respuesta al cliente por un fallo de escritura del medidor sería
    mucho peor.
    """
    client_id = client_id or _inquilino()
    if client_id is None:
        return

    session = get_session()
    try:
        fila = _fila(session, client_id, periodo_actual(), crear=True)
        fila.mensajes = (fila.mensajes or 0) + 1
        fila.tokens_in = (fila.tokens_in or 0) + max(0, int(tokens_in or 0))
        fila.tokens_out = (fila.tokens_out or 0) + max(0, int(tokens_out or 0))
        fila.actualizado = ahora_utc()
        session.commit()
    except Exception as e:                                # pragma: no cover
        print(f"[consumo] no se pudo anotar el uso de IA: {e}")
        session.rollback()
    finally:
        session.close()


def del_mes(client_id: int = None, periodo: str = None) -> dict:
    """Lo gastado en un mes. Ceros si ese cliente no ha usado la IA."""
    client_id = client_id or _inquilino()
    periodo = periodo or periodo_actual()
    vacio = {"periodo": periodo, "mensajes": 0, "tokens_in": 0, "tokens_out": 0}

    if client_id is None:
        return vacio

    session = get_session()
    try:
        fila = _fila(session, client_id, periodo)
        if fila is None:
            return vacio
        return {"periodo": periodo, "mensajes": fila.mensajes or 0,
                "tokens_in": fila.tokens_in or 0,
                "tokens_out": fila.tokens_out or 0}
    finally:
        session.close()


def supera_el_tope(client_id: int = None) -> bool:
    """
    ¿Este negocio ya gastó su cupo de IA del mes?

    Con el tope en 0 no consulta la base: es el camino de casi todos los
    clientes y esto corre dentro del webhook, que tiene prisa.
    """
    limite = config.IA_LIMITE_MENSUAL
    if limite <= 0:
        return False

    return del_mes(client_id)["mensajes"] >= limite


def restantes(client_id: int = None) -> int | None:
    """
    Cuántos mensajes de IA le quedan este mes. None si no tiene tope.

    Lo enseña el panel: un dueño que ve "te quedan 120" entiende por qué el
    bot dejó de interpretar, en vez de creer que se rompió.
    """
    limite = config.IA_LIMITE_MENSUAL
    if limite <= 0:
        return None
    return max(0, limite - del_mes(client_id)["mensajes"])


def uso_de_todos(periodo: str = None) -> list[dict]:
    """
    El consumo de cada cliente en un mes, para el super-admin.

    Cruza con `clients` para poder poner nombres y no ids. Ojo: esto tiene
    que correr **sin inquilino fijado**, o el filtro automático lo dejaría
    en un solo negocio (ver `database._filtrar_por_inquilino`).
    """
    from app.core.database import Client

    periodo = periodo or periodo_actual()

    session = get_session()
    try:
        filas = (session.query(Client, IAUso)
                 .outerjoin(IAUso, (IAUso.client_id == Client.id)
                            & (IAUso.periodo == periodo))
                 .order_by(Client.id).all())

        return [{
            "client_id": cliente.id,
            "nombre": cliente.nombre,
            "slug": cliente.slug,
            "active": cliente.active,
            "plan": cliente.plan,
            # Con esto se deduce el plan de los clientes de antes del
            # 23-sep-2026, que tienen una etiqueta libre (`planes.codigo_de`).
            "ia_contratada": cliente.ia_contratada,
            "ia_activa": cliente.ia_activa,
            "limite": cliente.ia_limite_mensual or 0,
            "mensajes": (uso.mensajes if uso else 0) or 0,
            "tokens_in": (uso.tokens_in if uso else 0) or 0,
            "tokens_out": (uso.tokens_out if uso else 0) or 0,
        } for cliente, uso in filas]
    finally:
        session.close()


def periodos_con_uso(limite: int = 12) -> list[str]:
    """Los meses de los que hay algo anotado, del más nuevo al más viejo."""
    session = get_session()
    try:
        filas = (session.query(IAUso.periodo)
                 .group_by(IAUso.periodo)
                 .order_by(func.max(IAUso.periodo).desc())
                 .limit(limite).all())
        return [f[0] for f in filas]
    finally:
        session.close()
