"""
PRUEBAS DE ROW-LEVEL SECURITY (solo PostgreSQL)
================================================
La otra suite (`test_multitenant.py`) comprueba que el CÓDIGO no mezcla
clientes. Esta comprueba que **la base tampoco los mezclaría aunque el
código se equivocara**: consulta en SQL crudo, saltándose el ORM y su
filtro, que es exactamente lo que RLS tiene que atajar.

    Si esta suite pasa con el ORM de por medio pero no en SQL crudo, no
    está probando nada: estaría comprobando el filtro de siempre.

POR QUÉ NO CORRE CON LAS DEMÁS
------------------------------
Necesita PostgreSQL, y en la máquina de desarrollo hay SQLite. Se le pasa
la base por variable de entorno, y sin ella no hace nada y devuelve 0:

    RLS_DATABASE_URL="postgresql://usuario:clave@host/base" python tests/test_rls.py

    ⚠️  NUNCA la de producción. Esta suite ESCRIBE y BORRA filas de prueba.

La URL es la "External Database URL" del panel de Render: la interna
(`dpg-…-a` a secas) solo resuelve dentro de Render y desde aquí no
conecta.

QUÉ COMPRUEBA, Y POR QUÉ CADA COSA
----------------------------------
1. Que las cerraduras están puestas en las ocho tablas, **forzadas**. Sin
   `FORCE`, la aplicación es la dueña de las tablas y se salta sus propias
   políticas: todo parecería bien y no protegería nada.
2. Que con un negocio anunciado, un `SELECT` a pelo solo devuelve lo suyo.
3. Que **no se puede escribir** una fila a nombre de otro negocio.
4. Que sin negocio anunciado se ve todo — la puerta que necesitan las
   migraciones, los scripts y /superadmin, y que es una decisión, no un
   descuido.
5. Que el anuncio no se queda pegado a la conexión cuando termina la
   transacción, que es lo que envenenaría a la siguiente petición.
"""
import os
import sys

PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROY)
os.chdir(PROY)

URL = os.environ.get("RLS_DATABASE_URL", "").strip()
if not URL:
    print("\n=== Row-Level Security ===")
    print("  (saltada: no hay RLS_DATABASE_URL, y RLS solo existe en PostgreSQL)")
    print("\n  Para correrla:")
    print('    RLS_DATABASE_URL="postgresql://..." python tests/test_rls.py')
    raise SystemExit(0)

# Tiene que estar puesta ANTES de importar nada de la app: `config` y
# `database` leen la URL al importarse.
os.environ["DATABASE_URL"] = URL

from app.core import database, tenencia          # noqa: E402

fallos = []


def check(nombre, condicion, detalle=""):
    linea = f"  {'[OK]' if condicion else '[X] '} {nombre}" + (
        f"  {detalle}" if detalle else "")
    try:
        print(linea)
    except UnicodeEncodeError:
        codificacion = sys.stdout.encoding or "ascii"
        print(linea.encode(codificacion, "replace").decode(codificacion))
    if not condicion:
        fallos.append(nombre)


print("\n=== Row-Level Security ===")
print(f"  base: {database.engine.url.render_as_string(hide_password=True)}")

if not database.ES_POSTGRES:
    print("  [X]  esa URL no es de PostgreSQL")
    raise SystemExit(1)


def crudo(sql, parametros=None, client_id=None):
    """
    SQL a pelo, sin ORM y por tanto **sin el filtro de siempre**.

    Si se pasa `client_id`, se anuncia igual que lo hace la aplicación en
    cada transacción (`database._anunciar_inquilino`).
    """
    with database.engine.begin() as conexion:
        if client_id is not None:
            database._fijar_inquilino_en_la_base(conexion, client_id)
        resultado = conexion.exec_driver_sql(sql, parametros or ())
        return resultado.fetchall() if resultado.returns_rows else []


# ── 0. El esquema, y dos negocios de prueba ──────────────────────────
#
# La base la construye Alembic, igual que en producción: si el esquema se
# hiciera aquí con create_all, no habría políticas que probar y la suite
# pasaría en verde sin comprobar nada.

from alembic import command                      # noqa: E402
from alembic.config import Config                # noqa: E402

# `migrations/env.py` toma la URL de `database.DATABASE_URL`, que salió de
# la variable de entorno de arriba: no hay que pasársela aquí.
command.upgrade(Config(os.path.join(PROY, "alembic.ini")), "head")

faltan = database.tablas_sin_cerradura()
check("las ocho tablas del inquilino tienen RLS, encendido y FORZADO",
      not faltan, f"sin cerradura: {faltan}" if faltan else "")

# Sin FORCE, el dueño de las tablas se salta sus políticas. La aplicación
# se conecta a Render como dueña, así que esto no es un detalle: es la
# diferencia entre proteger y aparentar que se protege.
forzadas = crudo("""
    SELECT c.relname FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = current_schema() AND c.relname = 'messages'
       AND c.relforcerowsecurity
""")
check("y el FORCE está de verdad en la tabla de mensajes", bool(forzadas))

session = database.get_session()
try:
    for cid, slug in ((901, "rls-uno"), (902, "rls-dos")):
        if not session.query(database.Client).filter_by(id=cid).first():
            session.add(database.Client(id=cid, slug=slug, nombre=slug,
                                        active=True,
                                        phone_number_id=f"9000000000{cid}"))
    session.commit()
finally:
    session.close()

crudo("DELETE FROM messages WHERE client_id IN (901, 902)")
crudo("DELETE FROM contacts WHERE client_id IN (901, 902)")

for cid, telefono in ((901, "573009010001"), (902, "573009020002")):
    with tenencia.usar(cid):
        s = database.get_session()
        try:
            s.add(database.Contact(phone=telefono, name=f"Cliente de {cid}"))
            s.commit()
        finally:
            s.close()

# ── 1. Leer: la base niega lo del otro ───────────────────────────────
filas = crudo("SELECT client_id, phone FROM contacts WHERE client_id IN (901, 902)",
              client_id=901)
check("en SQL CRUDO, con un negocio anunciado, solo se ven sus contactos",
      bool(filas) and all(f[0] == 901 for f in filas), str(filas)[:70])

filas = crudo("SELECT client_id FROM contacts WHERE client_id IN (901, 902)",
              client_id=902)
check("y al anunciar el otro, los suyos y ninguno del primero",
      bool(filas) and all(f[0] == 902 for f in filas), str(filas)[:70])

# El caso que de verdad importa: una consulta que PIDE lo del otro negocio
# a propósito. Es lo que haría un `filter_by` mal escrito o un script.
filas = crudo("SELECT client_id FROM contacts WHERE client_id = 902",
              client_id=901)
check("pedir explícitamente lo del otro negocio devuelve VACÍO",
      filas == [], str(filas)[:70])

# ── 2. Escribir: tampoco a nombre de otro ────────────────────────────
try:
    crudo("""INSERT INTO contacts (client_id, phone, name)
             VALUES (902, '573009029999', 'colado')""", client_id=901)
    colado = True
except Exception:
    colado = False

check("no se puede INSERTAR una fila a nombre de otro negocio", not colado)

filas = crudo("SELECT phone FROM contacts WHERE phone = '573009029999'")
check("y esa fila no quedó en la base", filas == [], str(filas)[:70])

# ── 3. Sin inquilino se ve todo: la puerta de los scripts ────────────
#
# Es una DECISIÓN, no un descuido: /superadmin, las migraciones y las
# limpiezas del arranque miran a todos los negocios. Está escrito en la
# migración y aquí se fija, para que nadie lo "arregle" sin querer.
filas = crudo("SELECT client_id FROM contacts WHERE client_id IN (901, 902)")
check("sin negocio anunciado se ven todos (los scripts y /superadmin)",
      len({f[0] for f in filas}) == 2, str(sorted({f[0] for f in filas})))

# ── 4. El anuncio no se queda pegado a la conexión ───────────────────
#
# Es `SET LOCAL`: vive lo que dure la transacción. Si sobreviviera, una
# conexión reutilizada del pool llegaría con el negocio del anterior
# puesto y la petición siguiente vería lo que no es suyo.
with database.engine.connect() as conexion:
    with conexion.begin():
        database._fijar_inquilino_en_la_base(conexion, 901)
        dentro = conexion.exec_driver_sql(
            "SELECT current_setting('app.client_id', true)").scalar()
    fuera = conexion.exec_driver_sql(
        "SELECT current_setting('app.client_id', true)").scalar()

check("el negocio anunciado dura lo que dura la transacción",
      dentro == "901" and fuera in (None, ""), f"dentro={dentro} fuera={fuera!r}")

# ── 5. Y la aplicación entera sigue funcionando con las cerraduras ───
with tenencia.usar(901):
    s = database.get_session()
    try:
        propios = s.query(database.Contact).count()
        ajeno = s.query(database.Contact).filter_by(client_id=902).count()
    finally:
        s.close()

check("el ORM sigue viendo lo suyo con RLS puesto", propios >= 1, f"{propios}")
check("y lo del otro le sigue dando cero", ajeno == 0, f"{ajeno}")

# ── Limpieza ─────────────────────────────────────────────────────────
crudo("DELETE FROM contacts WHERE client_id IN (901, 902)")
crudo("DELETE FROM clients WHERE id IN (901, 902)")

print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)}:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)

print("Row-Level Security: la base niega lo de otro negocio, no solo el código.")
raise SystemExit(0)
