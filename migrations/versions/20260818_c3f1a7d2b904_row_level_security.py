"""row level security

Pone la regla de aislamiento DENTRO de PostgreSQL.

Hasta ahora, lo que impedía que un negocio viera lo de otro era el filtro
del ORM (`database._filtrar_por_inquilino`): una regla que el código se
aplica a sí mismo antes de cada consulta. Funciona y está probada, pero
depende de que todo el código pase por ahí. Esto añade la segunda capa:
una consulta en SQL crudo, un script o un `filter_by` olvidado tampoco
pueden devolver filas de otro negocio.

CÓMO FUNCIONA
-------------
Cada transacción dice de quién es (`set_config('app.client_id', ..., true)`
en `database._anunciar_inquilino`) y cada tabla del inquilino lleva una
política que compara ese valor con su columna `client_id`.

    Sin inquilino anunciado, la política DEJA PASAR.

Es deliberado, y es la misma regla que el filtro del ORM: las migraciones,
las limpiezas del arranque, los scripts y `/superadmin` tienen que poder
mirar a todos los negocios. Protege lo que corre dentro de una petición
real —que es todo lo que atiende a un cliente— y no pretende ser una
barrera contra quien ya pueda ejecutar SQL arbitrario en la base.

FORCE, Y POR QUÉ SIN ESO NO SIRVE DE NADA
-----------------------------------------
En PostgreSQL, **el dueño de una tabla se salta sus propias políticas**, y
la aplicación se conecta a Render como dueña de la base. Sin
`FORCE ROW LEVEL SECURITY` esto se aplicaría sin error, sin fallo visible
y sin proteger nada — el peor resultado posible, porque parece hecho.
Por eso va aquí y por eso `tests/test_rls.py` lo comprueba leyendo de
verdad con el inquilino puesto.

SOLO POSTGRESQL
---------------
SQLite no tiene RLS (fue una de las razones para dejarlo). En la máquina
de desarrollo esta migración no hace nada, y el código funciona igual con
las cerraduras y sin ellas.

Revision ID: c3f1a7d2b904
Revises: b1c7d2e94a10
Create Date: 2026-08-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c3f1a7d2b904'
down_revision: Union[str, None] = 'b1c7d2e94a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Las mismas ocho de `database.MODELOS_DEL_INQUILINO`. `clients` no está:
# es la tabla que dice quién es quién, y filtrarla sería morderse la cola
# (nadie podría resolver a qué negocio pertenece un phone_number_id).
TABLAS = ("contacts", "messages", "leads", "ajustes", "push_subscriptions",
          "processed_messages", "panel_users", "ia_uso")

POLITICA = "aislar_inquilino"

# El valor anunciado en la transacción. `true` es missing_ok: si nadie lo
# fijó nunca, devuelve NULL en vez de reventar. Y al TERMINAR una
# transacción que sí lo fijó no vuelve a NULL: vuelve a la cadena vacía.
# O sea que hay que contar con los dos, y la cadena vacía es el caso
# normal en cualquier conexión reutilizada del pool.
ANUNCIADO = "current_setting('app.client_id', true)"

# NULLIF convierte la cadena vacía en NULL, y COALESCE la sustituye
# entonces por la propia columna: "client_id = client_id", que es cierto
# para toda fila. Sin inquilino anunciado, la política deja pasar.
#
#     ⚠️  NO escribir esto como
#         ANUNCIADO IS NULL OR ANUNCIADO = '' OR client_id = ANUNCIADO::int
#
# Parece lo mismo y no lo es: **SQL no garantiza que un OR corte en cuanto
# una parte es cierta**. PostgreSQL evalúa igualmente `''::int` y revienta
# con "invalid input syntax for type integer". Y no revienta al aplicar la
# migración, sino en la primera consulta que corra sin inquilino sobre una
# conexión ya usada — o sea, en producción y con el bot ya atendiendo.
# Lo cazó `tests/test_rls.py` en el ensayo, que para eso está.
CONDICION = ("client_id = COALESCE("
             f"NULLIF({ANUNCIADO}, '')::int, client_id)")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for tabla in TABLAS:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        # Sin esto, la aplicación (que es la dueña) se saltaría la
        # política y todo esto sería decoración. Ver la cabecera.
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {POLITICA} ON {tabla}")
        # USING filtra lo que se lee y lo que se toca; WITH CHECK impide
        # ESCRIBIR una fila a nombre de otro negocio, que es la mitad que
        # se olvida y la que dejaría datos cruzados de verdad.
        op.execute(f"""
            CREATE POLICY {POLITICA} ON {tabla}
                USING ({CONDICION})
                WITH CHECK ({CONDICION})
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for tabla in TABLAS:
        op.execute(f"DROP POLICY IF EXISTS {POLITICA} ON {tabla}")
        op.execute(f"ALTER TABLE {tabla} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabla} DISABLE ROW LEVEL SECURITY")
