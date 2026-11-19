"""Fecha del acta a partir del texto del PDF. Si el PDF está escaneado, aplica OCR."""
from __future__ import annotations

import collections
import datetime as dt
import re
import unicodedata

MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
         "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}

# Expresiones que indican la fecha del acta (de mayor a menor prioridad).
PRIORIDAD = ["FECHA DEL ACTA", "FECHA Y HORA", "FECHA DE ELABORACION", "FECHA DE VISITA",
             "FECHA DE ENTREGA", "FECHA DE INSTALACION", "EN LA CIUDAD DE"]
# Si aparecen justo antes de una fecha, esa fecha se descarta.
EXCLUIR = ["VENCIMIENTO", "VENCE", "VIGENCIA", "CONTRATO", "MODIFICACION", "HISTORIAL", "REFERENCIA"]

RX_NUMERICA = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)")
RX_LARGA = re.compile(
    r"(?<!\d)(\d{1,2})\s+(?:DIAS?\s+DEL\s+MES\s+)?(?:DE\s+)?(" + "|".join(MESES) + r")\s+(?:DE\s+)?(\d{4})(?!\d)"
)
VENTANA = 60          # caracteres de contexto previo que se revisan
MINIMO_TEXTO = 40     # por debajo de esto el PDF se considera escaneado


def _limpio(texto: str) -> str:
    """Mayúsculas sin tildes, conservando la longitud del texto."""
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode("ascii")
        salida.append(base or c)
    return "".join(salida).upper()


def _fecha(anio: int, mes: int, dia: int) -> dt.date | None:
    try:
        if not 2000 <= anio <= 2100:
            return None
        return dt.date(anio, mes, dia)
    except ValueError:
        return None


def fecha_desde_texto(texto: str) -> dict | None:
    """Busca la fecha del acta en el texto. Devuelve fecha, fragmento y confianza."""
    t = _limpio(texto)
    candidatas = []
    for m in RX_NUMERICA.finditer(t):
        candidatas.append((m.start(), m.end(), _fecha(int(m[3]), int(m[2]), int(m[1]))))
    for m in RX_LARGA.finditer(t):
        candidatas.append((m.start(), m.end(), _fecha(int(m[3]), MESES[m[2]], int(m[1]))))

    validas = []
    for ini, fin, f in candidatas:
        if f is None:
            continue
        previo = t[max(0, ini - VENTANA):ini]
        if any(x in previo for x in EXCLUIR):
            continue
        indices = [i for i, p in enumerate(PRIORIDAD) if p in previo]
        validas.append({"fecha": f, "ini": ini, "fin": fin, "prio": min(indices) if indices else None})

    if not validas:
        return None

    con_prioridad = [v for v in validas if v["prio"] is not None]
    if con_prioridad:
        elegida = min(con_prioridad, key=lambda v: (v["prio"], v["ini"]))
        confianza = "ALTA"
    else:
        mas_comun = collections.Counter(v["fecha"] for v in validas).most_common(1)[0][0]
        elegida = next(v for v in validas if v["fecha"] == mas_comun)
        confianza = "BAJA"

    fragmento = " ".join(t[max(0, elegida["ini"] - VENTANA):elegida["fin"] + 20].split())
    return {"fecha": elegida["fecha"], "fragmento": fragmento, "confianza": confianza}


def _ocr(doc) -> str:
    import pytesseract
    from PIL import Image

    partes = []
    for pagina in doc:
        pix = pagina.get_pixmap(dpi=300)
        imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        partes.append(pytesseract.image_to_string(imagen, lang="spa"))
    return "\n".join(partes)


def extraer_fecha_pdf(datos: bytes, usar_ocr: bool = True) -> dict | None:
    """Lee el PDF (texto o OCR) y devuelve la fecha, o None si no encuentra una.

    Lanza excepción si el PDF no se puede abrir.
    """
    import fitz  # PyMuPDF

    with fitz.open(stream=datos, filetype="pdf") as doc:
        texto = "\n".join(p.get_text() for p in doc)
        origen = "PDF_TEXTO"
        if len(texto.strip()) < MINIMO_TEXTO and usar_ocr:
            texto = _ocr(doc)
            origen = "PDF_OCR"
    res = fecha_desde_texto(texto)
    if res:
        res["fuente"] = origen
    return res
