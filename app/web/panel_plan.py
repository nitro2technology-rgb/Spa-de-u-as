"""
"MI PLAN", DESDE EL PANEL DEL DUEÑO
===================================
Qué contrató, a qué tiene derecho, cuánto está usando, cuándo vence y
cómo pagarnos. Solo el dueño: a quien entra por un área no le toca.

Las cuentas —qué estado tiene, qué se le dice— salen de `app/core/cobros.py`,
que es lo mismo que decide los correos de cobro. Así la pantalla y el
correo dicen lo mismo con las mismas fechas.
"""

import html
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import config
from app.core import cobros, consumo, equipo, planes, tenencia
from app.web import admin_ui

router = APIRouter(prefix="/admin", tags=["panel"])


def _e(valor) -> str:
    return html.escape(str(valor if valor is not None else ""))


def enlace_comprobante(negocio: str) -> str:
    """El WhatsApp de Nitro con el mensaje ya escrito."""
    texto = f"Hola, te envío el comprobante de pago de {negocio}."
    return f"https://wa.me/{planes.WHATSAPP_COBROS}?text={quote(texto)}"


def banda_de_cobro(quien) -> str:
    """
    La franja que avisa de un pago cercano o atrasado, para el dueño.

    Se pinta arriba de la lista de conversaciones: es lo que se ve cada vez
    que abre el panel. A un área no se le enseña: no es quien paga.
    """
    if quien is None or not quien.es_dueno:
        return ""
    try:
        c = cobros.cuenta_de(tenencia.actual())
    except Exception:
        return ""
    if c is None or c.estado not in (cobros.POR_VENCER, cobros.VENCIDO):
        return ""
    if c.estado == cobros.VENCIDO:
        clase = "cobro-banda vencido"
        texto = (f"Tu plan venció el {cobros.fecha_en_palabras(c.vence_el)}. "
                 f"El bot se pausa el {cobros.fecha_en_palabras(c.pausa_el)}.")
    else:
        cuando = ("hoy" if c.dias == 0 else "mañana" if c.dias == 1
                  else f"en {c.dias} días")
        clase = "cobro-banda"
        texto = f"Tu plan vence {cuando} ({cobros.fecha_en_palabras(c.vence_el)})."
    return (f'<a class="{clase}" href="/admin/mi-plan">{_e(texto)} '
            f'<strong>Ver cómo pagar →</strong></a>')


def _estado(c: cobros.Cuenta) -> tuple[str, str]:
    """(clase, frase) del estado de la cuenta, para la tarjeta."""
    if c.estado == cobros.SIN_COBRO:
        return "ok", "Sin pagos pendientes."
    if c.estado == cobros.AL_DIA:
        return "ok", f"Al día. Próximo pago: {cobros.fecha_en_palabras(c.vence_el)}."
    if c.estado == cobros.POR_VENCER:
        cuando = ("hoy" if c.dias == 0 else "mañana" if c.dias == 1
                  else f"en {c.dias} días")
        return "aviso", (f"Vence {cuando}, el "
                         f"{cobros.fecha_en_palabras(c.vence_el)}.")
    return "mal", (f"Venció el {cobros.fecha_en_palabras(c.vence_el)}. Si no "
                   f"recibimos el pago, el bot se pausa el "
                   f"{cobros.fecha_en_palabras(c.pausa_el)}.")


@router.get("/mi-plan", response_class=HTMLResponse)
def mi_plan(request: Request):
    sesion = admin_ui._sesion_valida(request)
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return admin_ui._pedir_login(
            admin_ui.CADUCADA if admin_ui._sesion_caducada(request) else "")
    if not quien.es_dueno:
        return RedirectResponse("/admin/inbox", status_code=303)

    c = cobros.cuenta_de(tenencia.actual())
    plan = c.plan if c else planes.PLANES[config.PLAN]
    clase, frase = _estado(c) if c else ("ok", "")

    incluye = "".join(f"<li>{_e(x)}</li>" for x in plan.incluye)

    areas = equipo.areas()
    cupo = config.MAX_DESTINOS_AVISOS
    usado_areas = (f"{len(areas)} de {cupo}" if cupo > 0
                   else "no incluidas en tu plan")
    ia_mes = consumo.del_mes()["mensajes"] if plan.ia else None
    uso_ia = (f"{ia_mes:,}".replace(",", ".") + " mensajes entendidos este mes"
              if plan.ia else "no incluida en tu plan")

    ultimo = ""
    if c and c.ultimo_pago_el:
        ultimo = (f'<p class="ajuste-nota">Último pago: '
                  f'{cobros.fecha_en_palabras(c.ultimo_pago_el)} · '
                  f'{planes.pesos(c.ultimo_pago_monto or 0)}.</p>')

    medios = "".join(
        f'<div class="plan-medio"><span>{_e(nombre)}</span>'
        f'<strong class="cifras">{_e(dato)}</strong></div>'
        for nombre, dato in planes.MEDIOS_DE_PAGO)

    comparar = "".join(f"""
          <div class="plan-opcion{" actual" if p.codigo == plan.codigo else ""}">
            <span class="plan-opcion-nombre">{_e(p.nombre)}</span>
            <strong class="cifras">{planes.pesos(p.precio)}</strong>
            <span class="plan-opcion-mes">al mes</span>
            <span>{"Con IA" if p.ia else "Sin IA"} ·
              {p.areas if p.areas else "sin"} área{"" if p.areas == 1 else "s"}</span>
            {'<em>Tu plan</em>' if p.codigo == plan.codigo else ""}
          </div>""" for p in (planes.PLANES[k] for k in planes.ORDEN))

    cambiar = (f"https://wa.me/{planes.WHATSAPP_COBROS}?text="
               + quote(f"Hola, quiero cambiar el plan de {config.BUSINESS_NAME}."))

    return admin_ui._renovar(HTMLResponse(admin_ui._pagina("Mi plan", f"""
      <div class="armazon">
        {admin_ui._rail("plan", quien)}

        <main class="agenda">
          <header class="agenda-cabecera">
            <div class="agenda-titulo">
              <h1>Mi plan</h1>
              <p class="apoyo">Lo que tienes contratado con Nitro 2Tech, cuándo
                 se paga y cómo.</p>
            </div>
          </header>

          <section class="ajuste plan-resumen">
            <div class="plan-cabeza">
              <div>
                <span class="plan-etiqueta">Plan</span>
                <h2>{_e(plan.nombre)}</h2>
              </div>
              <div class="plan-precio">
                <strong class="cifras">{planes.pesos(c.precio if c else plan.precio)}</strong>
                <span>al mes</span>
              </div>
            </div>
            <div class="plan-estado {clase}">{_e(frase)}</div>
            {ultimo}
          </section>

          <section class="ajuste">
            <h2>A qué tienes derecho</h2>
            <ul class="plan-incluye">{incluye}</ul>
            <div class="plan-uso">
              <div><span>Áreas de tu equipo</span><strong>{_e(usado_areas)}</strong></div>
              <div><span>IA</span><strong>{_e(uso_ia)}</strong></div>
            </div>
          </section>

          <section class="ajuste" id="como-pagar">
            <h2>Cómo pagar</h2>
            <p class="ajuste-apoyo">Paga el valor de tu plan y mándanos el
               comprobante por WhatsApp. Lo registramos y se corre tu fecha
               un mes.</p>
            {medios}
            <div class="ajuste-fila">
              <a class="boton-solido" target="_blank" rel="noopener"
                 href="{_e(enlace_comprobante(config.BUSINESS_NAME))}">Enviar el
                 comprobante por WhatsApp</a>
            </div>
            <p class="ajuste-nota">Te avisamos por correo una semana antes de
               cada vencimiento. Si el pago no llega, el bot sigue funcionando
               {planes.DIAS_DE_GRACIA} días más y después se pausa; no se borra
               nada, y vuelve en cuanto registramos el pago.</p>
          </section>

          <section class="ajuste">
            <h2>Los planes</h2>
            <div class="plan-comparar">{comparar}</div>
            <div class="ajuste-fila">
              <a class="boton-contorno" target="_blank" rel="noopener"
                 href="{_e(cambiar)}">Quiero cambiar de plan</a>
            </div>
          </section>

          {admin_ui._credito()}
        </main>
      </div>""", guiones=("panel-base.js",), pantalla_completa=True)),
        request, sesion)
