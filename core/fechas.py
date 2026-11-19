"""Fecha del acta a partir del PDF: texto, OCR si hace falta y, en último caso, metadatos."""
from __future__ import annotations

import collections
import datetime as dt
import functools
import logging
import os
import re
import unicodedata

log = logging.getLogger("actas")

MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
         "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}

# Expresiones que indican la fecha del acta (de mayor a menor prioridad).
PRIORIDAD = ["FECHA DEL ACTA", "FECHA Y HORA", "FECHA DE ELABORACION", "FECHA DE VISITA",
             "FECHA DE ENTREGA", "FECHA DE INSTALACION", "EN LA CIUDAD DE", "FECHA"]
# Si aparecen justo antes de una fecha (y después de cualquier rótulo de PRIORIDAD), esa fecha se descarta.
EXCLUIR = ["VENCIMIENTO", "VENCE", "VIGENCIA", "CONTRATO", "MODIFICACION", "HISTORIAL", "REFERENCIA"]

RX_NUMERICA = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)")
RX_ISO = re.compile(r"(?<!\d)(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)")
# "MARZO 15 DE 2024"
RX_MES_PRIMERO = re.compile(r"\b(" + "|".join(MESES) + r")\s+(\d{1,2})\s*(?:DE|,)?\s+(\d{4})(?!\d)")
RX_LARGA = re.compile(
    r"(?<!\d)(\d{1,2})\s+(?:DIAS?\s+DEL\s+MES\s+)?(?:DE\s+)?(" + "|".join(MESES) + r")\s+(?:DE\s+)?(\d{4})(?!\d)"
)
VENTANA = 60          # caracteres de contexto previo que se revisan


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
    for m in RX_ISO.finditer(t):
        candidatas.append((m.start(), m.end(), _fecha(int(m[1]), int(m[2]), int(m[3]))))
    for m in RX_MES_PRIMERO.finditer(t):
        candidatas.append((m.start(), m.end(), _fecha(int(m[3]), MESES[m[1]], int(m[2]))))
    for m in RX_LARGA.finditer(t):
        candidatas.append((m.start(), m.end(), _fecha(int(m[3]), MESES[m[2]], int(m[1]))))

    validas = []
    for ini, fin, f in candidatas:
        if f is None:
            continue
        previo = t[max(0, ini - VENTANA):ini]
        # "CONTRATO ... 2024 - 2026 ... FECHA 06/02/2026": el rótulo FECHA está más cerca, se conserva.
        if max(previo.rfind(x) for x in EXCLUIR) > max(previo.rfind(p) for p in PRIORIDAD):
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


# Rutas habituales del instalador de Tesseract en Windows (todos los usuarios / solo el usuario).
TESSERACT_WINDOWS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")]


@functools.lru_cache(maxsize=16)  # la fecha y los equipos leen el mismo PDF: OCR una sola vez
def ocr_pdf(datos: bytes) -> str:
    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image

    ruta = next((r for r in TESSERACT_WINDOWS if os.path.exists(r)), None)
    if ruta:
        pytesseract.pytesseract.tesseract_cmd = ruta
    partes = []
    with fitz.open(stream=datos, filetype="pdf") as doc:
        for pagina in doc:
            pix = pagina.get_pixmap(dpi=300)
            imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            # Hay páginas escaneadas de cabeza o de lado: se enderezan con el detector de orientación (osd).
            try:
                giro = pytesseract.image_to_osd(imagen, output_type=pytesseract.Output.DICT)["rotate"]
            except pytesseract.TesseractError:  # página casi vacía: no se puede detectar
                giro = 0
            if giro:
                imagen = imagen.rotate(-giro, expand=True)
            partes.append(pytesseract.image_to_string(imagen, lang="spa"))
    return "\n".join(partes)


def texto_pdf(datos: bytes, usar_ocr: bool = True) -> str:
    """Texto del PDF; si casi no tiene (escaneado), el del OCR."""
    import fitz  # PyMuPDF

    with fitz.open(stream=datos, filetype="pdf") as doc:
        texto = "\n".join(p.get_text() for p in doc)
    return ocr_pdf(datos) if usar_ocr and len(texto.strip()) < 40 else texto


def _fecha_metadatos(doc) -> dict | None:
    """Último recurso: fecha de creación guardada en el PDF ('D:20240315...')."""
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", doc.metadata.get("creationDate") or "")
    f = m and _fecha(int(m[1]), int(m[2]), int(m[3]))
    if not f:
        return None
    return {"fecha": f, "fragmento": "fecha de creación del archivo PDF", "confianza": "BAJA",
            "fuente": "PDF_METADATOS"}


def extraer_fecha_pdf(datos: bytes, usar_ocr: bool = True) -> dict | None:
    """Busca la fecha en el texto del PDF; si no la halla, aplica OCR; si tampoco, usa los metadatos.

    Lanza excepción si el PDF no se puede abrir.
    """
    import fitz  # PyMuPDF

    with fitz.open(stream=datos, filetype="pdf") as doc:
        res = fecha_desde_texto("\n".join(p.get_text() for p in doc))
        if res:
            res["fuente"] = "PDF_TEXTO"
            return res
        if usar_ocr:
            # El texto puede ser solo un encabezado con el cuerpo escaneado: se intenta OCR igual.
            try:
                res = fecha_desde_texto(ocr_pdf(datos))
            except Exception as e:  # noqa: BLE001
                log.warning("OCR no disponible: %s", e)
            if res:
                res["fuente"] = "PDF_OCR"
                return res
        return _fecha_metadatos(doc)
