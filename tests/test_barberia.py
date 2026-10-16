"""
PRUEBAS DEL PANEL DE BARBERÍAS — FASE 0
========================================
La entrada, los roles, el aislamiento entre barberías y las cuentas.
Levanta el servidor de verdad en un puerto suelto, como test_panel.py, y
lo ejercita por HTTP. La base es temporal y no sale ningún correo: el
envío se sustituye para poder leer lo que se habría mandado.

    python tests/test_barberia.py
"""

import os
import re
import sys
import tempfile
import threading
import time
from datetime import timedelta

PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROY)
os.chdir(PROY)

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "barberia.db").replace("\\", "/")
os.environ["ADMIN_API_KEY"] = "clave-barberia-prueba"
os.environ["PANEL_URL"] = "https://panel.ejemplo.test"
os.environ["SUPERADMIN_KEY"] = "clave-super-prueba"
os.environ.setdefault("SECRETS_KEY", "T2FhOFBTS0RqM3ZzWmJ4TkxxWXc5Y0hHdFJtRXVfMD0=")

import requests   # noqa: E402
import uvicorn    # noqa: E402

from app.core import acceso, correo, database, equipo, planes, tenencia   # noqa: E402
from app.barberia import cuentas, formato, nomina, operacion, permisos    # noqa: E402
from app.barberia import reportes, usuarios                                # noqa: E402
from app.barberia import modelos as m                                      # noqa: E402
from app.integrations import sheets_service                                # noqa: E402

sheets_service.asegurar_pestanas = lambda *a, **k: True

# Los correos no salen: se guardan para mirarlos.
CORREOS = []
correo.avisar = lambda destinos, asunto, cuerpo, *a, **k: CORREOS.append(
    (destinos, asunto, cuerpo))

from app import main   # noqa: E402

fallos = []


def check(nombre, condicion, extra=""):
    print(f"  {'[OK]' if condicion else '[X] '} {nombre}{'  ' + str(extra) if extra else ''}")
    if not condicion:
        fallos.append(nombre)


# ══════════════════════════════════════════════════════════════════════
#  LA BASE
# ══════════════════════════════════════════════════════════════════════

database.init_db()


def cliente(slug, nombre, plan, activo=True, barberia=True, **extra):
    s = database.SessionLocal()
    try:
        c = database.Client(slug=slug, nombre=nombre, active=activo, plan=plan,
                            barberia_contratada=barberia, **extra)
        s.add(c)
        s.commit()
        return c.id
    finally:
        s.close()


CLAVE = "clave-larga-1"

FILO = cliente("filo", "Filo Barbería", planes.BARBERIA_BOT_IA)
with tenencia.usar(FILO):
    CHAPINERO = cuentas.crear_sede(FILO, "Chapinero")
    USAQUEN = cuentas.crear_sede(FILO, "Usaquén")
    CEDRITOS = cuentas.crear_sede(FILO, "Cedritos")
    cuentas.crear_persona(FILO, "Ricardo Gómez", "ricardo", m.DUENO, [],
                          correo="ricardo@filo.co", telefono="300 111 2233",
                          clave=CLAVE)
    cuentas.crear_persona(FILO, "Sofía Restrepo", "sofia.r", m.ADMIN,
                          [CHAPINERO, USAQUEN], clave=CLAVE)
    cuentas.crear_persona(FILO, "Laura Pardo", "laura.p", m.RECEPCION,
                          [CHAPINERO], clave=CLAVE)
    ANDRES, _ = cuentas.crear_persona(FILO, "Andrés Martínez", "andres.m",
                                      m.BARBERO, [CHAPINERO], clave=CLAVE)
    _, TEMPORAL = cuentas.crear_persona(FILO, "Daniel Castro", "daniel.c",
                                        m.BARBERO, [USAQUEN])
    CAMILO, _ = cuentas.crear_persona(FILO, "Camilo Torres", "camilo.t",
                                      m.BARBERO, [CHAPINERO], clave=CLAVE)
    BORRADO, _ = cuentas.crear_persona(FILO, "Borrado Pérez", "borrado.p",
                                       m.BARBERO, [CHAPINERO], clave=CLAVE)
    s = database.get_session()
    p = s.get(m.Personal, CAMILO)
    p.activo = False
    s.get(database.PanelUser, p.panel_user_id).active = False
    s.get(m.Personal, BORRADO).eliminado_en = m.ahora()
    s.commit()
    s.close()

OTRA = cliente("otra", "Otra Barbería", planes.BARBERIA)
with tenencia.usar(OTRA):
    SEDE_OTRA = cuentas.crear_sede(OTRA, "Centro")
    cuentas.crear_persona(OTRA, "Olga Díaz", "olga", m.DUENO, [], clave=CLAVE)

PAUSADA = cliente("navaja", "Navaja Club", planes.BARBERIA, activo=False,
                  pausado_por="impago")
with tenencia.usar(PAUSADA):
    sede = cuentas.crear_sede(PAUSADA, "Centro")
    cuentas.crear_persona(PAUSADA, "Hernán Ruiz", "hernan", m.DUENO, [], clave=CLAVE)
    cuentas.crear_persona(PAUSADA, "Felipe Nieto", "pipe.n", m.BARBERO, [sede],
                          clave=CLAVE)

# Una barbería que dejó de tener el módulo, y el dueño del BOT (cliente 1)
# con su usuario de siempre.
SIN_MODULO = cliente("sinmodulo", "Sin Módulo", planes.BARBERIA)
with tenencia.usar(SIN_MODULO):
    cuentas.crear_sede(SIN_MODULO, "Única")
    cuentas.crear_persona(SIN_MODULO, "Samuel Mora", "samuel", m.DUENO, [], clave=CLAVE)
with tenencia.usar(database.CLIENTE_POR_DEFECTO):
    acceso.crear_usuario(database.CLIENTE_POR_DEFECTO, "dueno.bot", CLAVE)

tenencia.olvidar()


def quitar_modulo(client_id):
    s = database.SessionLocal()
    s.get(database.Client, client_id).barberia_contratada = False
    s.commit()
    s.close()
    tenencia.olvidar()


# ══════════════════════════════════════════════════════════════════════
#  EL SERVIDOR
# ══════════════════════════════════════════════════════════════════════

threading.Thread(target=lambda: uvicorn.run(main.app, port=8322, log_level="error"),
                 daemon=True).start()
BASE = "http://127.0.0.1:8322"
for _ in range(80):
    try:
        requests.get(BASE + "/", timeout=1)
        break
    except Exception:
        time.sleep(0.25)


def olvidar_frenos():
    cuentas.FRENO_USUARIO.clear()
    cuentas.FRENO_IP.clear()


def entrar(usuario, clave=CLAVE, recordar=False, ip=None):
    """Una sesión nueva. Devuelve (sesión, respuesta sin seguir redirección)."""
    s = requests.Session()
    cabeceras = {"X-Forwarded-For": ip} if ip else {}
    datos = {"usuario": usuario, "clave": clave}
    if recordar:
        datos["recordar"] = "1"
    r = s.post(BASE + "/entrar", data=datos, allow_redirects=False, headers=cabeceras)
    return s, r


def alerta(r):
    hallado = re.search(r'role="alert">([^<]*)', r.text)
    return hallado.group(1).strip() if hallado else ""


def destino(r):
    return r.headers.get("location", "")


# ══════════════════════════════════════════════════════════════════════
print("\nEl esquema")
# ══════════════════════════════════════════════════════════════════════

tablas = {t.__tablename__ for t in m.MODELOS}
check("las tablas de la barbería tienen el filtro del ORM",
      tablas <= {t.__tablename__ for t in database.MODELOS_DEL_INQUILINO})

en_migracion = set()
for archivo in ("20260924_e1b5c3a7d902_barberia_fase_0.py",
                "20260924_f2c6d4b8e013_barberia_fase_1.py",
                "20260924_a4d7e9b2c015_barberia_fase_2.py"):
    migracion = open(os.path.join(PROY, "migrations", "versions", archivo),
                     encoding="utf-8").read()
    en_migracion |= set(re.findall(r'"(barb_[a-z_]+)"',
                                   migracion.split("TABLAS = (")[1].split(")")[0]))
check("y todas tienen su política de RLS en la migración", en_migracion == tablas,
      sorted(tablas ^ en_migracion))

# ══════════════════════════════════════════════════════════════════════
print("\nLos planes")
# ══════════════════════════════════════════════════════════════════════

check("un negocio del bot no ve los planes de barbería",
      not set(planes.ORDEN) & set(planes.ORDEN_BARBERIA))
check("los tres planes del bot no cambiaron",
      [planes.PLANES[c].precio for c in planes.ORDEN] == [70_000, 100_000, 130_000]
      and all(planes.PLANES[c].bot and not planes.PLANES[c].barberia
              for c in planes.ORDEN))
check("el cobro reconoce un plan de barbería",
      planes.precio_de({"plan": planes.BARBERIA}) == 89_000)
check("los cupos salen del plan",
      (planes.cupo_de_sedes({"plan": planes.BARBERIA_BOT}),
       planes.cupo_de_barberos({"plan": planes.BARBERIA_BOT})) == (2, 8))
check("y lo pactado manda sobre el plan",
      planes.cupo_de_barberos({"plan": planes.BARBERIA, "max_barberos": 7}) == 7)
check("el plan de entrada no trae bot", not planes.PLANES[planes.BARBERIA].bot)

# ══════════════════════════════════════════════════════════════════════
print("\nEntrar")
# ══════════════════════════════════════════════════════════════════════

olvidar_frenos()
_, r = entrar("ricardo")
check("el dueño llega al resumen", destino(r) == "/b/resumen", destino(r))
_, r = entrar("sofia.r")
check("la administradora de sede también", destino(r) == "/b/resumen", destino(r))
_, r = entrar("laura.p")
check("recepción llega a la caja", destino(r) == "/b/caja", destino(r))
_, r = entrar("andres.m")
check("el barbero llega a su día", destino(r) == "/yo/dia", destino(r))
_, r = entrar("  Ricardo@FILO.co ")
check("se entra con el correo, sin importar mayúsculas", destino(r) == "/b/resumen")
_, r = entrar("300 111 2233")
check("y con el celular, con espacios", destino(r) == "/b/resumen")

_, r = entrar("", "")
check("vacío pide los dos datos", alerta(r) == "Escribe tu usuario y tu contraseña.")
check("y marca los dos campos", r.text.count("con-error") == 2)

olvidar_frenos()
_, r = entrar("ricardo", "mala")
check("clave mala dice cuántos intentos quedan",
      alerta(r) == "Usuario o contraseña incorrectos. Te quedan 4 intentos.", alerta(r))
check("y conserva lo escrito", 'value="ricardo"' in r.text)
_, r = entrar("nadie.existe", "mala")
check("un usuario que no existe dice lo mismo",
      alerta(r).startswith("Usuario o contraseña incorrectos."))
for _ in range(3):
    _, r = entrar("ricardo", "mala")
check("con un intento, en singular", alerta(r).endswith("Te queda 1 intento."), alerta(r))
_, r = entrar("ricardo", "mala")
check("al quinto se bloquea 15 minutos", alerta(r).startswith("Bloqueamos el acceso por 15"))
_, r = entrar("ricardo")
check("y bloqueado no entra ni con la clave buena", destino(r) == "")
_, r = entrar("ricardo", ip="203.0.113.9")
check("el bloqueo es por usuario + IP: desde otra IP sí entra",
      destino(r) == "/b/resumen", destino(r))
_, r = entrar("sofia.r")
check("y a otro usuario desde la misma IP no lo bloquea",
      destino(r) == "/b/resumen", destino(r))

olvidar_frenos()
_, r = entrar("camilo.t")
check("desactivado lo dice (con la clave correcta)",
      alerta(r) == "Este usuario está desactivado. Pídele al dueño que lo vuelva a activar.")
_, r = entrar("camilo.t", "mala")
check("con la clave mala no revela que existe",
      alerta(r).startswith("Usuario o contraseña incorrectos."))
_, r = entrar("borrado.p")
check("a alguien quitado no lo deja entrar",
      alerta(r).startswith("Usuario o contraseña incorrectos."))

_, r = entrar("hernan")
check("el dueño de una barbería pausada ve la pantalla 4c",
      "Navaja Club está en pausa" in r.text and "Pagar y reactivar" in r.text)
check("con el valor pendiente de su plan", "$89.000" in r.text)
_, r = entrar("pipe.n")
check("y su barbero, el aviso genérico",
      alerta(r) == "El panel no está disponible por ahora. Habla con el dueño.")
_, r = entrar("hernan", "mala")
check("con la clave mala no se entera nadie de la pausa", "en pausa" not in r.text)

_, r = entrar("dueno.bot")
check("un usuario del bot sin ficha de barbería no entra aquí",
      alerta(r).startswith("Usuario o contraseña incorrectos."))

# ══════════════════════════════════════════════════════════════════════
print("\nLa sesión y 'Recordarme'")
# ══════════════════════════════════════════════════════════════════════

olvidar_frenos()
_, r = entrar("ricardo", recordar=True)
cookie = r.headers.get("set-cookie", "")
check("recordado: la cookie dura 30 días", re.search(r"Max-Age=259\d{4}", cookie), cookie[:80])
_, r = entrar("ricardo")
cookie = r.headers.get("set-cookie", "")
check("sin recordar: cookie de sesión del navegador", "Max-Age" not in cookie)
check("httponly y samesite", "HttpOnly" in cookie and "SameSite=lax" in cookie)

texto, _ = cuentas.pase_para(FILO, 1, True)
check("un pase recordado se reconoce por su firma",
      cuentas.es_recordado(acceso.leer_pase(texto, FILO)))
texto, _ = cuentas.pase_para(FILO, 1, False)
check("y uno normal no", not cuentas.es_recordado(acceso.leer_pase(texto, FILO)))

sesion, _ = entrar("ricardo")
r = sesion.get(BASE + "/b/resumen")
check("el dueño ve su panel", r.status_code == 200 and "Filo Barbería" in r.text)
check("con las nueve secciones",
      all(f'href="/b/{s.clave}' in r.text for s in permisos.SECCIONES))
r = sesion.get(BASE + "/entrar", allow_redirects=False)
check("con sesión, /entrar lo manda a su panel", destino(r) == "/b/resumen")
sesion.get(BASE + "/salir")
r = sesion.get(BASE + "/b/resumen", allow_redirects=False)
check("después de salir no entra", destino(r).startswith("/entrar"))

# ══════════════════════════════════════════════════════════════════════
print("\nQuién ve qué")
# ══════════════════════════════════════════════════════════════════════

barbero, _ = entrar("andres.m")
r = barbero.get(BASE + "/b/caja", allow_redirects=False)
check("un barbero no entra a /b", destino(r) == "/yo/dia", destino(r))
r = barbero.get(BASE + "/yo/dia")
check("y ve su día", "Hola, Andrés" in r.text and "Hoy llevas" in r.text)

dueno, _ = entrar("ricardo")
r = dueno.get(BASE + "/yo/dia", allow_redirects=False)
check("el dueño no entra a /yo", destino(r) == "/b/resumen")

admin, _ = entrar("sofia.r")
for seccion in ("equipo", "usuarios", "sedes"):
    r = admin.get(BASE + f"/b/{seccion}", allow_redirects=False)
    check(f"la administradora de sede no entra a /b/{seccion}",
          destino(r) == "/b/resumen", destino(r))
r = admin.get(BASE + "/b/caja")
check("ni lo ve en la barra", 'href="/b/usuarios' not in r.text
      and 'href="/b/equipo' not in r.text)
check("y solo ve sus dos sedes", ">Chapinero<" in r.text and ">Usaquén<" in r.text
      and ">Cedritos<" not in r.text)
r = admin.get(BASE + f"/b/caja?sede={CEDRITOS}")
check("una sede ajena en la dirección se ignora",
      re.search(r'segmento activo"[^>]*>Todas<', r.text) is not None)

recepcion, _ = entrar("laura.p")
r = recepcion.get(BASE + "/b/resumen", allow_redirects=False)
check("recepción solo ve la caja", destino(r) == "/b/caja")
r = recepcion.get(BASE + "/b/caja")
check("y en el celular sus pestañas son Agenda y Caja",
      'class="pestanas"' in r.text and ">Agenda</a>" in r.text and ">Resumen</a>" not in r.text)

r = dueno.get(BASE + "/b/nada")
check("una sección que no existe da 404", r.status_code == 404)

# ══════════════════════════════════════════════════════════════════════
print("\nAislamiento entre barberías")
# ══════════════════════════════════════════════════════════════════════

olga, _ = entrar("olga")
r = olga.get(BASE + "/b/resumen")
check("otra barbería ve su nombre y no el de Filo",
      "Otra Barbería" in r.text and "Filo" not in r.text)
r = olga.get(BASE + f"/b/caja?sede={CHAPINERO}")
check("y una sede de Filo en la dirección no aparece", "Chapinero" not in r.text)

with tenencia.usar(OTRA):
    s = database.get_session()
    sedes = [x.nombre for x in s.query(m.Sede).all()]
    gente = [x.nombre for x in s.query(m.Personal).all()]
    s.close()
check("el filtro del ORM: bajo OTRA solo se ven sus sedes", sedes == ["Centro"], sedes)
check("y solo su gente", gente == ["Olga Díaz"], gente)

with tenencia.usar(FILO):
    persona = cuentas.persona_de(acceso.Pase(FILO, 99999, 0))
check("un pase con un usuario ajeno no es nadie", persona is None)

# ══════════════════════════════════════════════════════════════════════
print("\nEl panel del bot queda cerrado para el personal")
# ══════════════════════════════════════════════════════════════════════

r = barbero.get(BASE + "/admin/api/conversaciones")
check("un barbero no lee las conversaciones del bot", r.status_code == 401, r.status_code)
r = barbero.get(BASE + "/admin/inbox")
check("y /admin le pide entrar", 'action="/admin/login"' in r.text)
with tenencia.usar(FILO):
    s = database.get_session()
    uid_dueno = (s.query(m.Personal).filter_by(rol=m.DUENO).first().panel_user_id)
    uid_barbero = s.get(m.Personal, ANDRES).panel_user_id
    s.close()
    check("el dueño de la barbería sí es dueño del bot",
          equipo.de_pase(acceso.Pase(FILO, uid_dueno, 0)) is not None)
    check("el barbero no", equipo.de_pase(acceso.Pase(FILO, uid_barbero, 0)) is None)

# ══════════════════════════════════════════════════════════════════════
print("\nMódulo contratado")
# ══════════════════════════════════════════════════════════════════════

samuel, r = entrar("samuel")
check("con el módulo entra", destino(r) == "/b/resumen")
quitar_modulo(SIN_MODULO)
r = samuel.get(BASE + "/b/resumen", allow_redirects=False)
check("si se le quita, la sesión abierta deja de servir en la siguiente pantalla",
      destino(r).startswith("/entrar"), destino(r))
_, r = entrar("samuel")
check("y al entrar se le dice por qué",
      alerta(r).startswith("Tu plan no incluye el panel de la barbería"))

# ══════════════════════════════════════════════════════════════════════
print("\nClave temporal")
# ══════════════════════════════════════════════════════════════════════

check("la temporal lleva el nombre de la barbería", re.fullmatch(r"Filo-\d{4}", TEMPORAL),
      TEMPORAL)
daniel, r = entrar("daniel.c", TEMPORAL)
check("con clave temporal se exige cambiarla", destino(r) == "/cambiar-contrasena")
r = daniel.get(BASE + "/yo/dia", allow_redirects=False)
check("y no se abre nada más hasta hacerlo", destino(r) == "/cambiar-contrasena")
r = daniel.get(BASE + "/cambiar-contrasena")
check("no pide la actual (la acaba de escribir)", 'name="actual"' not in r.text)
r = daniel.post(BASE + "/cambiar-contrasena", data={"nueva": "corta", "repetida": "corta"})
check("rechaza una corta", "al menos 8" in alerta(r))
r = daniel.post(BASE + "/cambiar-contrasena",
                data={"nueva": "nueva-clave-1", "repetida": "otra-cosa-1"})
check("rechaza si no coinciden", "no coinciden" in alerta(r))
r = daniel.post(BASE + "/cambiar-contrasena", allow_redirects=False,
                data={"nueva": "nueva-clave-1", "repetida": "nueva-clave-1"})
check("guardada, llega a su día con el aviso", destino(r) == "/yo/dia?aviso=clave")
olvidar_frenos()
_, r = entrar("daniel.c", TEMPORAL)
check("la temporal ya no sirve", destino(r) == "")
_, r = entrar("daniel.c", "nueva-clave-1")
check("la nueva sí", destino(r) == "/yo/dia")

r = dueno.get(BASE + "/cambiar-contrasena")
check("sin clave temporal sí pide la actual", 'name="actual"' in r.text)
r = dueno.post(BASE + "/cambiar-contrasena",
               data={"actual": "mala", "nueva": "otra-clave-1", "repetida": "otra-clave-1"})
check("y la comprueba", alerta(r) == "La contraseña actual no es esa.")

# ══════════════════════════════════════════════════════════════════════
print("\nOlvidé mi contraseña")
# ══════════════════════════════════════════════════════════════════════

CORREOS.clear()
r = requests.post(BASE + "/recuperar", data={"identificador": "ricardo"},
                  headers={"Host": "atacante.example"})
check("con correo, sale el enlace", len(CORREOS) == 1)
check("la pantalla dice 'Revisa tu correo'", "Revisa tu correo" in r.text)
enlace = re.search(r"https?://\S+/restablecer/(\S+)", CORREOS[0][2])
check("el enlace apunta a PANEL_URL y no al Host de la petición",
      CORREOS[0][2].count("https://panel.ejemplo.test/restablecer/") == 1)
token = enlace.group(1)

r2 = requests.post(BASE + "/recuperar", data={"identificador": "nadie.existe"})
check("a un usuario que no existe se le responde lo mismo",
      "Revisa tu correo" in r2.text and len(CORREOS) == 1)
requests.post(BASE + "/recuperar", data={"identificador": "andres.m"})
check("sin correo no sale nada", len(CORREOS) == 1)
r = requests.post(BASE + "/recuperar", data={"identificador": " "})
check("vacío lo pide", alerta(r) == "Escribe tu usuario, correo o celular.")

r = requests.get(BASE + f"/restablecer/{token}")
check("el enlace abre el formulario", r.status_code == 200 and 'name="nueva"' in r.text)
r = requests.post(BASE + f"/restablecer/{token}", allow_redirects=False,
                  data={"nueva": "desde-el-correo", "repetida": "desde-el-correo"})
check("guarda y manda a entrar", destino(r) == "/entrar?aviso=clave")
r = requests.get(BASE + f"/restablecer/{token}")
check("el enlace sirve una sola vez", r.status_code == 410)
olvidar_frenos()
_, r = entrar("ricardo", "desde-el-correo")
check("y la clave nueva funciona", destino(r) == "/b/resumen")

cuentas.pedir_recuperacion("ricardo")
viejo = re.search(r"/restablecer/(\S+)", CORREOS[-1][2]).group(1)
with tenencia.usar(FILO):
    s = database.get_session()
    fila = s.query(m.Recuperacion).filter_by(token_hash=cuentas._hash_token(viejo)).first()
    fila.vence_en = m.ahora() - timedelta(minutes=1)
    s.commit()
    s.close()
check("un enlace vencido no sirve", requests.get(BASE + f"/restablecer/{viejo}").status_code == 410)

for _ in range(5):
    cuentas.pedir_recuperacion("ricardo")
with tenencia.usar(FILO):
    s = database.get_session()
    vigentes = (s.query(m.Recuperacion)
                .filter(m.Recuperacion.usado_en.is_(None),
                        m.Recuperacion.vence_en > m.ahora()).count())
    s.close()
check("no más de 3 enlaces vigentes por persona",
      vigentes == cuentas.ENLACES_VIGENTES_MAX, vigentes)

# ══════════════════════════════════════════════════════════════════════
print("\nAlta de personal")
# ══════════════════════════════════════════════════════════════════════

check("el usuario se sugiere del nombre", cuentas.sugerir_usuario("Daniel Castro") == "daniel.c")
check("sin tildes", cuentas.sugerir_usuario("Íñigo Núñez") == "inigo.n")


def falla_con(texto, **datos):
    base = dict(client_id=FILO, nombre="Nuevo Barbero", usuario="nuevo.b",
                rol=m.BARBERO, sedes=[CHAPINERO], clave=CLAVE)
    base.update(datos)
    try:
        with tenencia.usar(FILO):
            cuentas.crear_persona(**base)
        return False, "no falló"
    except ValueError as e:
        return texto in str(e), str(e)


check("falta el nombre", *falla_con("Falta el nombre.", nombre=" "))
check("falta el usuario", *falla_con("Falta el usuario", usuario=""))
check("usuario con caracteres raros", *falla_con("solo puede llevar", usuario="con espacio"))
check("usuario de otra barbería", *falla_con("Ya hay alguien con el usuario @olga", usuario="olga"))
check("ni el del dueño del bot (no se lo roba)",
      *falla_con("Ya hay alguien con el usuario @dueno.bot", usuario="dueno.bot"))
check("una sede ajena no cuenta", *falla_con("Elige al menos una sede.", sedes=[SEDE_OTRA]))

with tenencia.usar(OTRA):
    for i in range(planes.PLANES[planes.BARBERIA].barberos):
        cuentas.crear_persona(OTRA, f"Barbero {i}", f"b{i}.otra", m.BARBERO,
                              [SEDE_OTRA], clave=CLAVE)
    try:
        cuentas.crear_persona(OTRA, "Uno Más", "uno.mas", m.BARBERO, [SEDE_OTRA],
                              clave=CLAVE)
        lleno = ""
    except cuentas.CupoLleno as e:
        lleno = str(e)
check("el plan de entrada no admite un sexto barbero",
      lleno.startswith("Llegaste a los 5 barberos de tu plan"), lleno)
with tenencia.usar(OTRA):
    try:
        cuentas.crear_sede(OTRA, "Segunda")
        lleno = ""
    except cuentas.CupoLleno as e:
        lleno = str(e)
check("ni una segunda sede", lleno.startswith("Llegaste a la sede de tu plan"), lleno)

with tenencia.usar(FILO):
    s = database.get_session()
    creados = s.query(m.Actividad).filter_by(accion="USUARIO").count()
    s.close()
check("cada alta queda en Actividad", creados >= 7, creados)

# ══════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: cobrar")
# ══════════════════════════════════════════════════════════════════════

olvidar_frenos()
dueno_s, _ = entrar("ricardo", "desde-el-correo")
andres_s, _ = entrar("andres.m")
HOY = formato.hoy_en(formato.ZONA)


def en(client_id, funcion):
    with tenencia.usar(client_id):
        return funcion()


def persona_de(client_id, personal_id):
    def buscar():
        s = database.get_session()
        uid = s.get(m.Personal, personal_id).panel_user_id
        s.close()
        return cuentas.persona_de(acceso.Pase(client_id, uid, 0))
    return en(client_id, buscar)


def aviso_de(sesion, ruta):
    r = sesion.get(BASE + ruta)
    hallado = re.search(r'data-aviso="([^"]*)"', r.text)
    return hallado.group(1) if hallado else ""


cat = en(FILO, lambda: operacion.servicios_de_sede(CHAPINERO))
CORTE, COMBO, CEJAS = cat[0]["id"], cat[1]["id"], cat[3]["id"]
check("cada sede nace con el catálogo y sus precios",
      [x["nombre"] for x in cat[:2]] == ["Corte clásico", "Corte + barba"]
      and cat[0]["precio"] == 35000)
check("y las tres sedes lo tienen",
      all(en(FILO, lambda i=i: operacion.servicios_de_sede(i)) for i in (CHAPINERO, USAQUEN, CEDRITOS)))

r = andres_s.get(BASE + "/yo/dia?registrar=1")
check("la hoja de cobro trae los precios de su sede", "Corte clásico" in r.text and "$35.000" in r.text)

r = andres_s.post(BASE + "/yo/servicios", data={"sede_id": CHAPINERO, "metodo": "efectivo"})
check("sin servicios no cobra", r.status_code == 400 and alerta(r) == "Elige qué le hiciste.")
r = andres_s.post(BASE + "/yo/servicios", data={"sede_id": CHAPINERO, "servicios": [CORTE]})
check("sin método tampoco", r.status_code == 400 and alerta(r) == "Elige cómo pagó.")
r = andres_s.post(BASE + "/yo/servicios", data={"sede_id": USAQUEN, "servicios": [CORTE],
                                               "metodo": "efectivo"})
check("en una sede donde no trabaja no cobra", r.status_code == 400
      and alerta(r) == "No trabajas en esa sede.", alerta(r))

r = andres_s.post(BASE + "/yo/servicios", allow_redirects=False,
                  data={"sede_id": CHAPINERO, "servicios": [CORTE], "metodo": "efectivo",
                        "propina": "5000", "cliente": "300 999 8877"})
check("cobra y vuelve a su día", destino(r) == "/yo/dia", destino(r))
check("el aviso va en una cookie, no en la dirección", "?" not in destino(r)
      and "barb_aviso" in r.headers.get("set-cookie", ""))
check("y dice lo que ganó (50% de $35.000 + $5.000)",
      aviso_de(andres_s, "/yo/dia") == "Servicio registrado. Ganaste $22.500.")
check("el aviso sale una sola vez", aviso_de(andres_s, "/yo/dia") == "")
r = andres_s.get(BASE + "/yo/dia")
check("Hoy llevas suma su parte y la propina", '<p class="yo-llevas-cifra">$22.500</p>' in r.text)
check("y aparece en 'Ya hiciste' con el celular del cliente", "300 999 8877" in r.text)

r = andres_s.post(BASE + "/yo/servicios", data={
    "sede_id": CHAPINERO, "servicios": [COMBO], "metodo": "dividido", "efectivo": "$50.000"})
check("en dividido el efectivo no puede ser todo", r.status_code == 400
      and "entre $1 y $49.999" in alerta(r), alerta(r))
check("y la hoja conserva lo elegido", f'value="{COMBO}"\n                   checked' in r.text
      or re.search(rf'value="{COMBO}"[^>]*checked', r.text) is not None)
r = andres_s.post(BASE + "/yo/servicios", allow_redirects=False, data={
    "sede_id": CHAPINERO, "servicios": [COMBO], "metodo": "dividido", "efectivo": "$20.000"})
check("dividido válido se registra", destino(r) == "/yo/dia")

cajas = en(FILO, lambda: operacion.cajas_de(persona_de(FILO, 1), None, HOY))
chap = next(c for c in cajas if c["sede_id"] == CHAPINERO)
check("la caja de la sede se abrió sola con el primer cobro", chap["abierta"] and chap["base"] == 0)
check("lo vendido incluye propinas ($40.000 + $50.000)", chap["vendido"] == 90000, chap["vendido"])
check("cada parte del dividido suma a su método",
      chap["por_metodo"].get(m.EFECTIVO) == 60000 and chap["por_metodo"].get(m.TRANSFERENCIA) == 30000)
check("debería haber = base + efectivo − gastos de caja", chap["esperado"] == 60000)

acts = en(FILO, lambda: reportes.actividad(persona_de(FILO, 1), "caja", HOY))
check("la apertura automática queda en Actividad",
      any("al registrar un cobro" in a["verbo"] for a in acts))

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: anular")
# ══════════════════════════════════════════════════════════════════════

def citas_de(personal_id):
    def q():
        s = database.get_session()
        filas = [(c.id, c.estado) for c in s.query(m.Cita).filter_by(barbero_id=personal_id)
                 .order_by(m.Cita.id)]
        s.close()
        return filas
    return en(FILO, q)


PRIMERA = citas_de(ANDRES)[0][0]
daniel_s, _ = entrar("daniel.c", "nueva-clave-1")
daniel_s.post(BASE + f"/yo/servicios/{PRIMERA}/anular", data={"motivo": "Quedó repetido"})
check("otro barbero no puede anular un servicio ajeno", citas_de(ANDRES)[0][1] == m.COMPLETADA)
olga = en(OTRA, lambda: cuentas.persona_de(acceso.Pase(OTRA, en(OTRA, lambda: database.get_session()
          .query(m.Personal).filter_by(rol=m.DUENO).first().panel_user_id), 0)))
try:
    en(OTRA, lambda: operacion.anular(olga, PRIMERA, "x", HOY))
    ajena = False
except operacion.Error:
    ajena = True
check("ni el dueño de OTRA barbería (el filtro del inquilino la esconde)", ajena)
laura = persona_de(FILO, en(FILO, lambda: database.get_session().query(m.Personal)
                            .filter_by(rol=m.RECEPCION).first().id))
try:
    en(FILO, lambda: operacion.anular(laura, PRIMERA, "x", HOY))
    recep = False
except operacion.Error:
    recep = True
check("recepción no anula", recep)

r = andres_s.post(BASE + f"/yo/servicios/{PRIMERA}/anular", data={"motivo": ""})
check("sin motivo no anula", r.status_code == 400 and alerta(r) == "Elige por qué lo anulas.")
r = andres_s.post(BASE + f"/yo/servicios/{PRIMERA}/anular", allow_redirects=False,
                  data={"motivo": "Lo registré por error"})
check("con motivo, anulado", destino(r) == "/yo/dia" and citas_de(ANDRES)[0][1] == m.ANULADA)
r = andres_s.get(BASE + "/yo/dia")
check("Hoy llevas ya no lo cuenta (solo el combo: 50% de $50.000)",
      '<p class="yo-llevas-cifra">$25.000</p>' in r.text)
check("y se ve tachado con su motivo", "Anulado: Lo registré por error" in r.text)
chap = next(c for c in en(FILO, lambda: operacion.cajas_de(persona_de(FILO, 1), None, HOY))
            if c["sede_id"] == CHAPINERO)
check("la caja deja de contar lo anulado", chap["vendido"] == 50000 and chap["esperado"] == 20000,
      (chap["vendido"], chap["esperado"]))
r = dueno_s.get(BASE + "/b/actividad?filtro=anulaciones")
check("el dueño lo ve en Actividad con el motivo", "anuló un servicio" in r.text
      and "Motivo: Lo registré por error" in r.text)

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: caja y gastos")
# ══════════════════════════════════════════════════════════════════════

r = dueno_s.post(BASE + "/b/gastos", allow_redirects=False, data={
    "descripcion": "Café", "monto": "$5.000", "categoria": "Insumos", "tipo": "VARIABLE",
    "sede_id": CHAPINERO, "de_la_caja": "1"})
check("un gasto pagado de la caja se registra", destino(r) == "/b/gastos")
chap = next(c for c in en(FILO, lambda: operacion.cajas_de(persona_de(FILO, 1), None, HOY))
            if c["sede_id"] == CHAPINERO)
check("y resta del arqueo", chap["gastos"] == 5000 and chap["esperado"] == 15000)
r = dueno_s.post(BASE + "/b/gastos", data={"descripcion": "", "monto": "", "sede_id": CHAPINERO})
check("un gasto sin concepto no se guarda", r.status_code == 400
      and alerta(r) == "Escribe en qué se gastó.")
r = dueno_s.post(BASE + f"/b/caja/{chap['caja']}/cerrar", data={"contado": ""})
check("cerrar sin conteo no cierra", r.status_code == 400 and alerta(r) == "Escribe cuánto contaste.")
r = dueno_s.post(BASE + f"/b/caja/{chap['caja']}/cerrar", allow_redirects=False,
                 data={"contado": "$10.000"})
check("cerrar con faltante lo dice", destino(r) == "/b/caja"
      and aviso_de(dueno_s, "/b/caja") == "Caja cerrada. Falta $5.000.")
r = dueno_s.post(BASE + f"/b/caja/{chap['caja']}/cerrar", data={"contado": "$10.000"})
check("una caja cerrada no se vuelve a cerrar", r.status_code == 400
      and alerta(r) == "Esa caja ya está cerrada.")
r = dueno_s.post(BASE + "/b/gastos", data={"descripcion": "Más café", "monto": "$1.000",
                                            "sede_id": CHAPINERO, "de_la_caja": "1"})
check("sin caja abierta no se paga un gasto de la caja", r.status_code == 400
      and "está cerrada" in alerta(r))
with tenencia.usar(FILO):
    try:
        operacion.cerrar_caja(persona_de(FILO, 1), chap["caja"], 0)
    except operacion.Error:
        pass
    s = database.get_session()
    guardada = s.get(m.Caja, chap["caja"])
    check("lo guardado al cerrar queda congelado",
          (guardada.efectivo_esperado, guardada.efectivo_contado, guardada.diferencia)
          == (15000, 10000, -5000))
    s.close()
check("un número que llega del código no se multiplica (el fallo de '241000.00')",
      operacion.dinero("$394.000") == 394000)

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: nómina")
# ══════════════════════════════════════════════════════════════════════

def fila_de(nombre):
    d = en(FILO, lambda: nomina.filas(persona_de(FILO, 1), None, HOY))
    return next((f for f in d["filas"] if f["nombre"] == nombre), None)


andres = fila_de("Andrés Martínez")
check("la liquidación cuenta solo lo no anulado", andres["comisiones"] == 25000
      and andres["propinas"] == 0 and andres["total"] == 25000, andres["total"])
check("un barbero desactivado sin trabajo no sale", fila_de("Camilo Torres") is None)
r = dueno_s.post(BASE + "/b/equipo/adelanto", allow_redirects=False,
                 data={"personal_id": ANDRES, "monto": "$10.000", "nota": ""})
check("un adelanto se registra", destino(r) == "/b/equipo")
check("y se descuenta", fila_de("Andrés Martínez")["total"] == 15000)
r = dueno_s.post(BASE + f"/b/equipo/{ANDRES}/aprobar", allow_redirects=False)
aprobada = fila_de("Andrés Martínez")
check("aprobar congela la liquidación", aprobada["estado"] == m.APROBADA
      and aprobada["total"] == 15000)
andres_s.post(BASE + "/yo/servicios", data={"sede_id": CHAPINERO, "servicios": [CORTE],
                                             "metodo": "tarjeta"})
check("un cobro después de aprobar no la cambia", fila_de("Andrés Martínez")["total"] == 15000)
check("pero sí aparece en Hoy llevas", '<p class="yo-llevas-cifra">$42.500</p>'
      in andres_s.get(BASE + "/yo/dia").text)
dueno_s.post(BASE + f"/b/equipo/liquidacion/{aprobada['liquidacion_id']}/pagar")
check("marcar pagada", fila_de("Andrés Martínez")["estado"] == m.PAGADA)
dueno_s.post(BASE + f"/b/equipo/liquidacion/{aprobada['liquidacion_id']}/pagar")
check("pagada es final", fila_de("Andrés Martínez")["estado"] == m.PAGADA)

sofia_s, _ = entrar("sofia.r")
r = sofia_s.post(BASE + f"/b/equipo/{ANDRES}/esquema", allow_redirects=False,
                 data={"esquema": m.COMISION, "porcentaje": "90"})
check("la administradora de sede no cambia la nómina", destino(r) == "/b/resumen")
r = dueno_s.post(BASE + f"/b/equipo/{ANDRES}/esquema", allow_redirects=False,
                 data={"esquema": m.COMISION, "porcentaje": "60", "meta": "$1.000.000"})
check("el dueño sí", destino(r) == "/b/equipo")
andres_s.post(BASE + "/yo/servicios", data={"sede_id": CHAPINERO, "servicios": [CORTE],
                                             "metodo": "tarjeta"})
ultimos = en(FILO, lambda: [(cs.porcentaje_barbero, cs.monto_barbero) for cs in
                            database.get_session().query(m.CitaServicio)
                            .order_by(m.CitaServicio.id).all()[-2:]])
check("el porcentaje nuevo vale para lo nuevo; lo cobrado queda congelado",
      ultimos == [(50, 17500), (60, 21000)], ultimos)

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: precios, sedes y resumen")
# ══════════════════════════════════════════════════════════════════════

r = dueno_s.post(BASE + "/b/sedes/precios", allow_redirects=False,
                 data={f"precio_{CORTE}_{USAQUEN}": "$38.000"})
check("cambiar un precio", destino(r) == "/b/sedes"
      and en(FILO, lambda: operacion.servicios_de_sede(USAQUEN))[0]["precio"] == 38000)
check("queda en Actividad con el antes y el después",
      "Corte clásico en Usaquén pasó de $35.000 a $38.000"
      in dueno_s.get(BASE + "/b/actividad?filtro=precios").text)
r = dueno_s.post(BASE + "/b/sedes/precios", data={f"precio_{CORTE}_{USAQUEN}": "$0"})
check("un precio en cero no se guarda", r.status_code == 400)
r = sofia_s.post(BASE + "/b/sedes/precios", allow_redirects=False,
                 data={f"precio_{CORTE}_{USAQUEN}": "$1.000"})
check("la administradora de sede no cambia precios", destino(r) == "/b/resumen"
      and en(FILO, lambda: operacion.servicios_de_sede(USAQUEN))[0]["precio"] == 38000)
r = dueno_s.post(BASE + "/b/sedes/nueva", data={"nombre": "Cuarta"})
check("no se agrega una sede por encima del cupo", r.status_code == 400
      and "Llegaste a las 3 sedes" in alerta(r), alerta(r))

res = en(FILO, lambda: reportes.resumen(persona_de(FILO, 1), None, "hoy", HOY))
cobrado = en(FILO, lambda: sum(cs.precio for cs in database.get_session().query(m.CitaServicio)
                                .join(m.Cita, m.Cita.id == m.CitaServicio.cita_id)
                                .filter(m.Cita.estado == m.COMPLETADA)))
check("el resumen suma lo cobrado sin anulados", res["ingresos"] == cobrado, (res["ingresos"], cobrado))
check("'Para revisar' avisa el faltante y la anulación",
      any("faltaron $5.000" in x["texto"] for x in res["revisar"])
      and any("anulado" in x["texto"] for x in res["revisar"]))
for periodo in ("hoy", "semana", "mes"):
    r = dueno_s.get(BASE + f"/b/resumen?periodo={periodo}")
    check(f"el resumen de {periodo} se pinta", r.status_code == 200 and "Ganancia neta" in r.text)

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: usuarios")
# ══════════════════════════════════════════════════════════════════════

r = dueno_s.get(BASE + "/b/usuarios?nuevo=1")
check("'Agregar usuario' trae una temporal con el nombre de la barbería",
      re.search(r'name="temporal" value="Filo-\d{4}"', r.text) is not None)
r = dueno_s.post(BASE + "/b/usuarios", allow_redirects=False, data={
    "nombre": "Pedro Pérez", "usuario": "pedro.p", "contacto": "pedro@filo.co",
    "rol": m.BARBERO, "sedes": [CHAPINERO], "temporal": "Filo-1234"})
check("alta de un barbero", destino(r) == "/b/usuarios")
check("con el aviso del diseño", aviso_de(dueno_s, "/b/usuarios")
      == "Usuario creado. Compártele @pedro.p y la contraseña temporal.")
olvidar_frenos()
pedro_s, r = entrar("pedro.p", "Filo-1234")
check("entra con la temporal que vio el dueño, y se le exige cambiarla",
      destino(r) == "/cambiar-contrasena")
r = dueno_s.post(BASE + "/b/usuarios", data={"nombre": "Otro", "usuario": "pedro.p",
                                              "rol": m.BARBERO, "sedes": [CHAPINERO]})
check("un usuario repetido no se guarda", r.status_code == 400
      and alerta(r) == "Ya hay alguien con el usuario @pedro.p. Prueba con otro.")
check("y el panel sigue abierto con lo escrito", 'value="Otro"' in r.text and 'class="cajon"' in r.text)

with tenencia.usar(FILO):
    s = database.get_session()
    PEDRO = s.query(m.Personal).filter_by(nombre="Pedro Pérez").first().id
    s.close()
dueno_s.post(BASE + f"/b/usuarios/{PEDRO}/acceso", data={"activo": "0"})
_, r = entrar("pedro.p", "Filo-1234")
check("con el acceso apagado no entra", alerta(r).startswith("Este usuario está desactivado"))
r = pedro_s.get(BASE + "/yo/dia", allow_redirects=False)
check("y su sesión abierta deja de servir", destino(r).startswith("/entrar"))
dueno_s.post(BASE + f"/b/usuarios/{PEDRO}/quitar")
_, r = entrar("pedro.p", "Filo-1234")
check("quitado, ya no entra", alerta(r).startswith("Usuario o contraseña incorrectos"))
r = dueno_s.post(BASE + "/b/usuarios", allow_redirects=False, data={
    "nombre": "Pedro Nuevo", "usuario": "pedro.p", "rol": m.BARBERO, "sedes": [CHAPINERO]})
check("y su nombre de usuario queda libre para otro", destino(r) == "/b/usuarios")
yo = persona_de(FILO, 1)
for accion in (lambda: usuarios.quitar(yo, yo.personal_id),
               lambda: usuarios.cambiar_acceso(yo, yo.personal_id, False)):
    try:
        en(FILO, accion)
        propio = False
    except operacion.Error:
        propio = True
    check("el dueño no se puede quitar ni apagar a sí mismo", propio)
r = dueno_s.post(BASE + f"/b/usuarios/{ANDRES}/restablecer")
temporal = re.search(r"Contraseña temporal: <strong>(Filo-\d{4})", r.text)
check("restablecer enseña la temporal nueva", temporal is not None)
olvidar_frenos()
_, r = entrar("andres.m", temporal.group(1) if temporal else "x")
check("y con ella se exige cambiarla", destino(r) == "/cambiar-contrasena")
r = andres_s.post(BASE + "/b/usuarios", allow_redirects=False,
                  data={"nombre": "Intruso", "usuario": "intruso", "rol": m.DUENO})
check("un barbero no puede dar de alta usuarios", destino(r) in ("/yo/dia", "/cambiar-contrasena")
      or destino(r).startswith("/entrar"))

# ══════════════════════════════════════════════════════════════════════
print("\nFase 1: consola Nitro2Tech")
# ══════════════════════════════════════════════════════════════════════

r = requests.get(BASE + "/superadmin/barberias", allow_redirects=False)
check("sin sesión del super-admin no se entra", destino(r) == "/superadmin/login")
r = dueno_s.get(BASE + "/superadmin/barberias", allow_redirects=False)
check("ni con la sesión del dueño de una barbería", destino(r) == "/superadmin/login")
sa = requests.Session()
sa.post(BASE + "/superadmin/login", data={"clave": "clave-super-prueba"})
r = sa.get(BASE + "/superadmin/barberias")
check("el super-admin ve las barberías", "Filo Barbería" in r.text and "Navaja Club" in r.text)
r = sa.post(BASE + "/superadmin/barberias", data={"nombre": "El Bigote", "dueno": "Óscar Niño",
                                                   "correo": "malo", "plan": planes.BARBERIA})
check("el alta valida el correo", alerta(r) == "Escribe un correo válido para enviarle el acceso.")
r = sa.post(BASE + "/superadmin/barberias", data={
    "nombre": "El Bigote", "sede": "Laureles", "dueno": "Óscar Niño", "correo": "oscar@bigote.co",
    "plan": planes.BARBERIA, "prueba": "1"})
alta = re.search(r"el usuario <strong>@([a-z0-9._]+)</strong> y la contraseña <strong>(Nitro-\d{4})", r.text)
check("el alta crea la barbería y el acceso del dueño", alta is not None)
olvidar_frenos()
_, r = entrar(alta.group(1), alta.group(2)) if alta else (None, r)
check("el dueño nuevo entra y cambia la clave", destino(r) == "/cambiar-contrasena")
check("y le llegó el correo de bienvenida", any("Tu acceso a El Bigote" in c[1] for c in CORREOS))
BIGOTE = next(f["id"] for f in __import__("app.barberia.consola", fromlist=["x"]).barberias()
              if f["nombre"] == "El Bigote")
r = sa.post(BASE + "/superadmin/barberias", data={
    "nombre": "Otra", "dueno": "Óscar", "correo": "oscar@bigote.co", "plan": planes.BARBERIA})
check("un correo que ya es dueño de otra barbería no se repite",
      alerta(r) == "Ese correo ya es el dueño de otra barbería.")
sa.post(BASE + f"/superadmin/barberias/{BIGOTE}/pausa", data={"motivo": "revision"})
_, r = entrar(alta.group(1), alta.group(2))
check("pausada desde la consola, el dueño ve la pantalla de pausa",
      "está en pausa" in r.text and "Estamos revisando la cuenta." in r.text)
sa.post(BASE + f"/superadmin/barberias/{BIGOTE}/reactivar")
_, r = entrar(alta.group(1), alta.group(2))
check("reactivada, vuelve a entrar", destino(r) == "/cambiar-contrasena")
r = sa.post(BASE + f"/superadmin/barberias/{BIGOTE}/limites", data={"sedes": "0", "barberos": "5"})
check("los límites no bajan del uso", r.status_code == 400 and "por debajo" in alerta(r))
sa.post(BASE + f"/superadmin/barberias/{BIGOTE}/plan", data={"plan": planes.BARBERIA_BOT})
c = tenencia.por_id(BIGOTE)
check("cambiar de plan enciende el bot", c.fila["plan"] == planes.BARBERIA_BOT
      and c.fila["bot_contratado"] is True)
r = sa.post(BASE + f"/superadmin/barberias/{BIGOTE}/plan", data={"plan": planes.PRO})
check("pero no a un plan del bot", r.status_code == 400)


# ══════════════════════════════════════════════════════════════════════
print("\nFase 2: la agenda")
# ══════════════════════════════════════════════════════════════════════

from datetime import datetime as _dt, time as _time, timedelta as _td   # noqa: E402
from app.barberia import agenda                                          # noqa: E402

MANANA = HOY + _td(days=1)
with tenencia.usar(FILO):
    TOMAS, _ = cuentas.crear_persona(FILO, "Tomás Bernal", "tomas.b", m.BARBERO,
                                     [CHAPINERO], clave=CLAVE)
olvidar_frenos()
tomas_s, _ = entrar("tomas.b")
corte = en(FILO, lambda: operacion.servicios_de_sede(CHAPINERO))[0]

check("cada sede nace con su horario",
      en(FILO, lambda: agenda.texto_horario(agenda.horario_de_sede(CHAPINERO)))
      == "Lun a sáb 8 a. m. a 8 p. m., dom 10 a. m. a 4 p. m.")
libres = en(FILO, lambda: list(agenda.huecos_de(CHAPINERO, TOMAS, MANANA, corte["minutos"])))
check("mañana hay huecos para Tomás", len(libres) > 10, len(libres))
PRIMERO = libres[0]
cita_a, _ = en(FILO, lambda: agenda.reservar(CHAPINERO, TOMAS, corte["id"], PRIMERO,
                                              origen=m.PANEL))
try:
    en(FILO, lambda: agenda.reservar(CHAPINERO, TOMAS, corte["id"], PRIMERO, origen=m.PANEL))
    doble = False
except agenda.Ocupado:
    doble = True
check("la misma hora no se reserva dos veces", doble)
check("y ya no se ofrece",
      PRIMERO not in en(FILO, lambda: agenda.huecos_de(CHAPINERO, TOMAS, MANANA, corte["minutos"])))
try:
    en(OTRA, lambda: agenda.reservar(CHAPINERO, TOMAS, corte["id"], libres[5], origen=m.PANEL))
    ajena = False
except operacion.Error:
    ajena = True
check("otra barbería no puede agendar en una sede de Filo", ajena)

r = dueno_s.post(BASE + "/b/agenda/bloqueo", allow_redirects=False, data={
    "sede_id": CHAPINERO, "personal_id": TOMAS, "fecha": MANANA.isoformat(),
    "desde": "14:00", "hasta": "15:00", "motivo": "Almuerzo"})
check("bloquear un rato", destino(r).startswith("/b/agenda"))
tras = en(FILO, lambda: agenda.huecos_de(CHAPINERO, TOMAS, MANANA, corte["minutos"]))
check("y en ese rato no se agenda (tampoco 13:30, que pisaría las 14)",
      not any(formato.a_local(t).strftime("%H:%M") in ("13:30", "14:00", "14:30") for t in tras))
r = dueno_s.post(BASE + "/b/agenda/bloqueo", data={
    "sede_id": CHAPINERO, "fecha": MANANA.isoformat(), "desde": "15:00", "hasta": "14:00"})
check("un bloqueo al revés no se guarda", r.status_code == 400
      and alerta(r) == "El bloqueo termina antes de empezar.")

hueco = list(tras)[3]
r = dueno_s.post(BASE + "/b/agenda/cita", allow_redirects=False, data={
    "sede_id": CHAPINERO, "barbero": TOMAS, "servicio": corte["id"],
    "inicio": hueco.isoformat(), "cliente": "300 555 1212"})
check("agendar desde el panel", destino(r).startswith("/b/agenda"), destino(r))
r = dueno_s.post(BASE + "/b/agenda/cita", data={
    "sede_id": CHAPINERO, "barbero": TOMAS, "servicio": corte["id"],
    "inicio": hueco.isoformat(), "cliente": "Otro"})
check("la misma hora desde el panel se rechaza", r.status_code == 400
      and alerta(r) == "Ese horario ya se ocupó. Elige otro.")
r = dueno_s.get(BASE + f"/b/agenda?sede={CHAPINERO}&fecha={MANANA.isoformat()}")
check("la agenda la pinta con el cliente", "300 555 1212" in r.text and "Tomás Bernal" in r.text)
check("y Actividad dice que se agendó", "agendó una cita"
      in dueno_s.get(BASE + "/b/actividad").text)
recep_s, _ = entrar("laura.p")
check("recepción ve la agenda", recep_s.get(BASE + "/b/agenda").status_code == 200)
check("el barbero no", destino(tomas_s.get(BASE + "/b/agenda", allow_redirects=False)) == "/yo/dia")

dueno_s.post(BASE + f"/b/agenda/cita/{cita_a}/estado", data={"estado": m.NO_ASISTIO})
check("marcar que no vino", en(FILO, lambda: agenda.cita(cita_a))["estado"] == m.NO_ASISTIO)
check("y el hueco queda libre", PRIMERO in en(FILO, lambda: agenda.huecos_de(
    CHAPINERO, TOMAS, MANANA, corte["minutos"])))
cita_b = en(FILO, lambda: [c["id"] for c in agenda.agenda_dia(CHAPINERO, MANANA)["citas"]
                           if c["cliente"] == "300 555 1212"][0])
dueno_s.post(BASE + f"/b/agenda/cita/{cita_b}/cancelar", data={"motivo": "Llamó a cancelar"})
check("cancelar una cita", en(FILO, lambda: agenda.cita(cita_b))["estado"] == m.CANCELADA)
r = dueno_s.post(BASE + f"/b/agenda/cita/{cita_b}/cancelar", allow_redirects=False)
check("una cancelada no se vuelve a cancelar",
      aviso_de(dueno_s, "/b/agenda") == "Esa cita ya no se puede cancelar.")

horario = {"abierto_0": "1", "desde_0": "10:00", "hasta_0": "12:00"}
r = dueno_s.post(BASE + f"/b/sedes/{USAQUEN}/horario", allow_redirects=False, data=horario)
check("cambiar el horario de una sede", destino(r) == "/b/sedes"
      and en(FILO, lambda: agenda.texto_horario(agenda.horario_de_sede(USAQUEN)))
      == "Lun 10 a. m. a 12 p. m.")
# Usaquén y no Cedritos: una sede sin barberos no tiene huecos ningún día.
dias = en(FILO, lambda: agenda.dias_con_huecos(USAQUEN, None, 40, HOY, 5))
check("y solo se ofrecen los lunes", dias and all(d.weekday() == 0 for d, _ in dias))
r = dueno_s.post(BASE + f"/b/sedes/{CEDRITOS}/horario",
                 data={"abierto_1": "1", "desde_1": "18:00", "hasta_1": "09:00"})
check("un horario que cierra antes de abrir no se guarda", r.status_code == 400
      and "cierra antes de abrir" in alerta(r))
r = sofia_s.post(BASE + f"/b/sedes/{CHAPINERO}/horario", allow_redirects=False, data=horario)
check("la administradora de sede no cambia horarios", destino(r) == "/b/resumen")

cli_id = en(FILO, lambda: agenda.cita(cita_b))["cliente_id"]
r = dueno_s.post(BASE + f"/b/clientes/{cli_id}/nota", allow_redirects=False,
                 data={"nota": "Degradado bajo", "volver": "https://sitio-malo.test/robo"})
check("la nota del cliente se guarda", en(FILO, lambda: agenda.cita(cita_b))["nota"]
      == "Degradado bajo")
check("y 'volver' no lleva fuera del panel", destino(r) == "/b/agenda")

# ── "Mi día" con citas ──
def cita_hoy(barbero, minutos_desde_ahora, estado=m.CONFIRMADA, cliente=None):
    def crear():
        s = database.get_session()
        inicio = m.ahora() + _td(minutes=minutos_desde_ahora)
        c = m.Cita(sede_id=CHAPINERO, barbero_id=barbero, inicio=inicio,
                   fin=inicio + _td(minutes=40), estado=estado, origen=m.WHATSAPP,
                   servicio_id=corte["id"], cliente_id=cliente)
        s.add(c)
        s.commit()
        i = c.id
        s.close()
        return i
    return en(FILO, crear)


proxima = cita_hoy(TOMAS, 1, cliente=cli_id)
r = tomas_s.get(BASE + "/yo/dia")
check("el barbero ve su siguiente cita con la nota del cliente",
      "Tu siguiente cita" in r.text and "Degradado bajo" in r.text)
daniel_s.post(BASE + f"/yo/citas/{proxima}/empezar")
check("otro barbero no la puede empezar", en(FILO, lambda: agenda.cita(proxima))["estado"]
      == m.CONFIRMADA)
tomas_s.post(BASE + f"/yo/citas/{proxima}/empezar")
check("él sí", en(FILO, lambda: agenda.cita(proxima))["estado"] == m.EN_CURSO
      and "Atendiendo ahora" in tomas_s.get(BASE + "/yo/dia").text)
r = tomas_s.get(BASE + f"/yo/dia?registrar=1&cita={proxima}")
check("'Cobrar' abre la hoja con su nombre y el servicio marcado",
      "Cobrar a 300 555 1212" in r.text
      and re.search(rf'value="{corte["id"]}"[^>]*checked', r.text) is not None)
antes = en(FILO, lambda: database.get_session().query(m.Cita).count())
r = tomas_s.post(BASE + "/yo/servicios", allow_redirects=False, data={
    "sede_id": CHAPINERO, "servicios": [corte["id"]], "metodo": "efectivo", "propina": "0",
    "cita_id": proxima})
check("cobrar la cita la completa", destino(r) == "/yo/dia"
      and en(FILO, lambda: agenda.cita(proxima))["estado"] == m.COMPLETADA)
check("sin crear otra visita", en(FILO, lambda: database.get_session().query(m.Cita).count()) == antes)
r = tomas_s.post(BASE + "/yo/servicios", data={
    "sede_id": CHAPINERO, "servicios": [corte["id"]], "metodo": "efectivo", "cita_id": proxima})
check("una cita cobrada no se cobra dos veces", r.status_code == 400
      and alerta(r) == "Esa cita ya se cobró o se canceló.")
tomas_s.post(BASE + "/yo/servicios", data={"sede_id": CHAPINERO, "servicios": [corte["id"]],
                                           "metodo": "efectivo"})
ultima = en(FILO, lambda: database.get_session().query(m.Cita).order_by(m.Cita.id.desc()).first())
check("un cliente sin cita queda como terminado ahora (no ocupa lo que viene)",
      m.en_utc(ultima.fin) <= m.ahora() + _td(seconds=5))

vieja = cita_hoy(TOMAS, -180)
res = en(FILO, lambda: reportes.resumen(persona_de(FILO, 1), None, "hoy", HOY))
check("'Para revisar' avisa una cita que pasó sin cobro",
      any("no hay cobro registrado" in x["texto"] for x in res["revisar"]), res["revisar"])
res = en(FILO, lambda: reportes.resumen(persona_de(FILO, 1), None, "mes", HOY))
check("la ocupación ya se calcula", isinstance(res["ocupacion"], int), res["ocupacion"])
dueno_s.post(BASE + f"/b/agenda/cita/{vieja}/estado", data={"estado": m.NO_ASISTIO})

# ══════════════════════════════════════════════════════════════════════
print("\nFase 2: el bot agenda en la barbería")
# ══════════════════════════════════════════════════════════════════════

from app.bot import bot_logic, whatsapp_client                           # noqa: E402
from app.barberia import bot as bbot, recordatorios                      # noqa: E402

ENVIOS = []


class _Resp:
    status_code = 200

    def json(self):
        return {"messages": [{"id": "wamid.prueba"}]}


def _guardar_envio(tipo):
    def enviar(to, *args, **kw):
        ENVIOS.append((tipo, to, args))
        return _Resp()
    return enviar


for nombre in ("send_text_message", "send_button_message", "send_list_message",
               "send_template_message"):
    setattr(whatsapp_client, nombre, _guardar_envio(nombre))


def ids_de(envio):
    """Los ids de filas o botones del último envío interactivo."""
    tipo, _, args = envio
    opciones = args[2] if tipo == "send_list_message" else args[1]
    return [o["id"] for o in opciones]


s = database.SessionLocal()
fila = s.get(database.Client, FILO)
fila.proveedor_agenda = "barberia"
s.commit()
s.close()
tenencia.olvidar()

TEL = "573017654321"
N = [0]


def escribe(**kw):
    N[0] += 1
    with tenencia.usar(FILO):
        bot_logic.handle_incoming_message(TEL, "interactive" if ("list_id" in kw or "button_id" in kw)
                                          else "text", message_id=f"wamid.b{N[0]}", **kw)


escribe(text="Hola")                        # crea el contacto (y abre la ventana de 24 h)
with tenencia.usar(FILO):
    ses = database.get_session()
    contacto = ses.query(database.Contact).filter_by(phone=TEL).first()
    contacto.name = "Julián Prueba"
    ENVIOS.clear()
    bot_logic._ofrecer_dias(contacto, ses)
    ses.commit()
    estado = contacto.state
    ses.close()
check("en una barbería, agendar pregunta la sede (no va a Google)",
      estado == "BARB_SEDE" and f"bsede_{CHAPINERO}" in ids_de(ENVIOS[-1]))
escribe(list_id=f"bsede_{CHAPINERO}")
check("después, el servicio con su precio",
      f"bserv_{corte['id']}" in ids_de(ENVIOS[-1]) and "¿Qué te vas a hacer?" in ENVIOS[-1][2][0])
escribe(text="blablá")
check("un texto suelto vuelve a preguntar lo mismo", f"bserv_{corte['id']}" in ids_de(ENVIOS[-1]))
escribe(list_id=f"bserv_{corte['id']}")
check("después, con quién (y 'el que esté libre')", "bbarb_0" in ids_de(ENVIOS[-1])
      and f"bbarb_{TOMAS}" in ids_de(ENVIOS[-1]))
escribe(list_id=f"bbarb_{TOMAS}")
dias_ids = ids_de(ENVIOS[-1])
check("después, los días con huecos (10 como mucho)", 0 < len(dias_ids) <= 10
      and all(i.startswith("bdia_") for i in dias_ids))
escribe(list_id=f"bdia_{MANANA.isoformat()}")
horas_ids = ids_de(ENVIOS[-1])
check("después, las horas de ese día (10 como mucho)", 0 < len(horas_ids) <= 10)
elegida = _dt.fromisoformat(horas_ids[0][len("bhora_"):])
escribe(list_id=horas_ids[0])
confirmacion = next((e for e in reversed(ENVIOS) if "quedó tu cita" in str(e[2])), None)
check("reserva y confirma con servicio, barbero, sede y precio",
      confirmacion is not None and "Corte clásico con Tomás" in str(confirmacion[2])
      and "$35.000" in str(confirmacion[2]))
with tenencia.usar(FILO):
    ses = database.get_session()
    nueva = (ses.query(m.Cita).filter_by(origen=m.WHATSAPP, barbero_id=TOMAS)
             .order_by(m.Cita.id.desc()).first())
    lead = ses.query(database.Lead).order_by(database.Lead.id.desc()).first()
    ses.close()
check("la cita entra por WhatsApp y confirmada, a la hora elegida",
      nueva is not None and nueva.estado == m.CONFIRMADA and m.en_utc(nueva.inicio) == elegida)
check("y queda un Lead que la enlaza", lead.google_event_id == f"barb:{nueva.id}")
check("la agenda del panel la ve con su origen",
      "WhatsApp" in dueno_s.get(BASE + f"/b/agenda?sede={CHAPINERO}&fecha={MANANA.isoformat()}").text)

with tenencia.usar(FILO):
    ses = database.get_session()
    contacto = ses.query(database.Contact).filter_by(phone=TEL).first()
    bot_logic._gestionar_cita(contacto, ses, "cancelar")
    ses.commit()
    ses.close()
check("cancelar desde el bot la cancela en la agenda (no en Google)",
      en(FILO, lambda: agenda.cita(nueva.id))["estado"] == m.CANCELADA)

# ── el recordatorio ──
with tenencia.usar(FILO):
    cli = bbot._cliente_de(database.get_session().query(database.Contact).filter_by(phone=TEL).first())
pronto = cita_hoy(TOMAS, 60, estado=m.CONFIRMADA, cliente=cli)
ENVIOS.clear()
recordatorios.recordar_negocio(FILO)
boton = next((e for e in ENVIOS if e[0] == "send_button_message"), None)
check("el recordatorio sale con 'Confirmo' y 'Cancelar'",
      boton is not None and ids_de(boton) == [f"brec_ok_{pronto}", f"brec_no_{pronto}"])
ENVIOS.clear()
recordatorios.recordar_negocio(FILO)
check("y sale una sola vez", not ENVIOS)
OTRO = "573019999999"
N[0] += 1
with tenencia.usar(FILO):
    bot_logic.handle_incoming_message(OTRO, "interactive", button_id=f"brec_no_{pronto}",
                                      message_id=f"wamid.b{N[0]}")
check("el botón de otro número no cancela la cita ajena",
      en(FILO, lambda: agenda.cita(pronto))["estado"] == m.CONFIRMADA)
escribe(button_id=f"brec_no_{pronto}")
check("'Cancelar' del recordatorio la cancela", en(FILO, lambda: agenda.cita(pronto))["estado"]
      == m.CANCELADA)
with tenencia.usar(OTRA):
    check("un negocio con Google Calendar no entra al flujo de barbería", not bbot.es_barberia())
check("sin inquilino (el bot de siempre) tampoco, y sin reventar", not bbot.es_barberia())


print()
if fallos:
    print(f"FALLARON {len(fallos)}:")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("Todo en orden.")
sys.exit(0)
