"""el paquete de IA se contrata, y los avisos se reparten por area

Dos cosas que se piden desde el mismo sitio —/superadmin— y que hasta
ahora no se podían decir.

1. `clients.ia_contratada`
--------------------------
Hasta ahora la puerta del plan Pro era "¿hay clave de Gemini?"
(`cerebro.hay_clave`). Esa no es la pregunta: **la clave la ponemos
nosotros y es la misma para todos**, así que cualquier cliente podía
entrar a su panel, darle a "Encender IA" y cargarnos el consumo sin haber
comprado el paquete.

La columna separa lo comercial de lo operativo, que estaban mezclados:

    ia_contratada   lo vendimos. Solo se toca desde /superadmin.
    ia_activa       si lo contrató, cómo nace: encendido o apagado.
    ajuste plan_ia  lo que el dueño eligió después en su panel.

En False, `cerebro.plan_activo()` devuelve siempre "basico" y el panel del
cliente no enseña el control. Las dos cosas, no solo la segunda: esconder
un botón mientras el endpoint sigue aceptando la petición no es una
puerta, es un adorno.

Nace en **False para todos**, incluido el cliente 1. Es lo correcto aunque
obligue a marcar a mano a quien ya lo tenga: el valor por defecto de algo
que se cobra tiene que ser "no lo compró". Quien ya lo tenga se marca en
su ficha, y son dos clics.

    ⚠️  Al desplegar esto, cualquier cliente con la IA encendida se queda
        en plan Básico hasta que se le marque la casilla. El bot NO se
        rompe: responde con el menú, que es exactamente lo que hace hoy
        cuando Gemini falla o se acaba el cupo.

2. Los destinos de los avisos
-----------------------------
No llevan columna: viven en `negocio_config`, junto al resto del contenido
del negocio (`[avisos].destinos`), porque son texto que se edita desde el
mismo editor y cambian con el negocio, no con el esquema. Por eso esta
migración no los toca — se anotan aquí para que quien lea el historial
sepa dónde buscarlos.

Bajar es seguro: se pierde qué clientes tenían la IA contratada.

Revision ID: f7c3a9e21b48
Revises: d4b8e1067c25
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "f7c3a9e21b48"
down_revision = "d4b8e1067c25"
branch_labels = None
depends_on = None


def upgrade():
    # `server_default` además del `default` del modelo: las filas que YA
    # existen necesitan un valor, y `default` de SQLAlchemy solo actúa al
    # insertar desde el ORM. Sin esto, la columna queda NULL en los
    # clientes viejos y `nullable=False` revienta la migración.
    #
    # `sa.false()` y no la cadena "0". Las dos funcionan —PostgreSQL acepta
    # '0' como literal booleano— pero solo esta se lee igual en los dos
    # motores: SQLAlchemy la escribe como `DEFAULT false` en PostgreSQL y
    # `DEFAULT (0)` en SQLite. Con la cadena, el que lea esto tiene que
    # saberse las reglas de conversión de PG para estar seguro, y una
    # migración que hay que verificar dos veces es una migración que
    # alguien va a dar por buena sin verificar. Producción es PostgreSQL y
    # aquí se prueba contra SQLite; esa distancia se cubre no dependiendo
    # de ninguna conversión implícita.
    op.add_column("clients", sa.Column(
        "ia_contratada", sa.Boolean(), nullable=False,
        server_default=sa.false()))


def downgrade():
    op.drop_column("clients", "ia_contratada")
