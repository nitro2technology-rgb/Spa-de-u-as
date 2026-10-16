"""
DE UN DOCUMENTO A UN PDF
=========================
Convierte `docs/META_VERIFICACION.md` en un PDF que se pueda imprimir o
mandar por correo.

    python scripts/pdf_de_documento.py       (necesita: pip install fpdf2)

El .md es la fuente; el PDF es una copia para leer. Existe este script
para que no se separen: un PDF que nadie sabe regenerar acaba diciendo
algo distinto del texto que sí se mantiene.

No tiene nada que ver con el bot. `fpdf2` no está en requirements.txt a
propósito: el servidor no lo necesita.

Es un renderizador MÍNIMO: entiende solo lo que ese documento usa
(titulos, parrafos, listas, citas, negrita, codigo entre acentos graves y
separadores). No pretende ser un conversor de Markdown; pretende que el
documento se pueda leer en papel.
"""
import os
import re

from fpdf import FPDF

RAIZ = r"C:\Nico\Nitro2Tech\Servicios\Automatizaciones Whatsapp\Bot +IA\Codigo"
ORIGEN = os.path.join(RAIZ, "docs", "META_VERIFICACION.md")
DESTINO = os.path.join(RAIZ, "docs", "META_VERIFICACION.pdf")

TINTA = (28, 33, 46)
TENUE = (110, 118, 135)
ACENTO = (37, 99, 235)
CAJA = (243, 245, 250)


class Documento(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*TENUE)
        self.cell(0, 6, "Verificacion de negocio ante Meta  ·  Nitro 2Tech",
                  align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*TENUE)
        self.cell(0, 10, str(self.page_no()), align="C")


def limpiar(texto: str) -> str:
    """
    Las fuentes de serie del PDF son latin-1. Se cambian los caracteres
    que no caben por su equivalente, en vez de dejar que reviente.
    """
    reemplazos = {
        "—": "-", "–": "-", "→": "->", "←": "<-", "↓": "|", "“": '"',
        "”": '"', "‘": "'", "’": "'", "…": "...", "•": "-", "✅": "[ok]",
        "⬜": "[  ]", "🔄": "[en curso]", "≤": "<=", "·": "-",
    }
    for viejo, nuevo in reemplazos.items():
        texto = texto.replace(viejo, nuevo)
    return texto.encode("latin-1", "replace").decode("latin-1")


def escribir_rico(pdf, texto, alto=5.6):
    """Un párrafo con **negrita** y `código` dentro."""
    partes = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", texto)
    for parte in partes:
        if not parte:
            continue
        if parte.startswith("**") and parte.endswith("**"):
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(*TINTA)
            pdf.write(alto, limpiar(parte[2:-2]))
        elif parte.startswith("`") and parte.endswith("`"):
            pdf.set_font("Courier", "", 9.5)
            pdf.set_text_color(*ACENTO)
            pdf.write(alto, limpiar(parte[1:-1]))
        else:
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(*TINTA)
            pdf.write(alto, limpiar(parte))
    pdf.ln(alto)


def render():
    lineas = open(ORIGEN, encoding="utf-8").read().splitlines()

    pdf = Documento(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()

    en_cita = []

    def volcar_cita():
        if not en_cita:
            return
        # Las citas van en una caja: son las advertencias que cuestan
        # dinero si se saltan.
        texto = " ".join(en_cita)
        en_cita.clear()
        pdf.ln(2)
        y0 = pdf.get_y()
        pdf.set_fill_color(*CAJA)
        pdf.set_draw_color(*ACENTO)
        pdf.set_left_margin(26)
        pdf.set_x(26)
        escribir_rico(pdf, texto, alto=5.4)
        y1 = pdf.get_y()
        pdf.set_left_margin(20)
        pdf.set_draw_color(*ACENTO)
        pdf.set_line_width(1.2)
        pdf.line(22, y0 - 1, 22, y1)
        pdf.set_line_width(0.2)
        pdf.ln(3)

    for cruda in lineas:
        linea = cruda.rstrip()

        if linea.startswith("> "):
            en_cita.append(linea[2:].strip())
            continue
        volcar_cita()

        if not linea:
            pdf.ln(2.5)
            continue

        if linea.startswith("---"):
            pdf.ln(2)
            pdf.set_draw_color(220, 224, 232)
            pdf.line(20, pdf.get_y(), 190, pdf.get_y())
            pdf.ln(4)
            continue

        if linea.startswith("### "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11.5)
            pdf.set_text_color(*TINTA)
            pdf.multi_cell(0, 6, limpiar(linea[4:]))
            pdf.ln(1)
            continue

        if linea.startswith("## "):
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(*ACENTO)
            pdf.multi_cell(0, 7.5, limpiar(linea[3:]))
            pdf.ln(1.5)
            continue

        if linea.startswith("# "):
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_text_color(*TINTA)
            pdf.multi_cell(0, 10, limpiar(linea[2:]))
            pdf.ln(2)
            continue

        if linea.startswith("*") and linea.endswith("*") and not linea.startswith("**"):
            pdf.set_font("Helvetica", "I", 9.5)
            pdf.set_text_color(*TENUE)
            pdf.multi_cell(0, 5.5, limpiar(linea.strip("*")))
            pdf.ln(1)
            continue

        # Lista con viñeta o numerada
        marca = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", linea)
        if marca:
            sangria = 20 + (4 if marca.group(1) else 0)
            pdf.set_left_margin(sangria + 6)
            pdf.set_x(sangria)
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(*ACENTO)
            simbolo = marca.group(2) if marca.group(2)[0].isdigit() else "-"
            pdf.write(5.6, f"{simbolo} ")
            escribir_rico(pdf, marca.group(3))
            pdf.set_left_margin(20)
            continue

        # Bloque de texto tal cual (los pasos de la cadena, el esquema)
        if cruda.startswith("    "):
            pdf.set_font("Courier", "", 9)
            pdf.set_text_color(*TENUE)
            pdf.set_x(26)
            pdf.multi_cell(0, 4.6, limpiar(linea.strip()))
            continue

        escribir_rico(pdf, linea)

    volcar_cita()
    pdf.output(DESTINO)
    print(f"PDF escrito: {DESTINO}")
    print(f"paginas: {pdf.page_no()}  ·  {os.path.getsize(DESTINO) // 1024} KB")


if __name__ == "__main__":
    render()
