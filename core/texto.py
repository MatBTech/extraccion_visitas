"""Normalización de textos y reconocimiento de actas, sedes y fechas en nombres de carpeta."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

SEPARADORES = re.compile(r"[\s_\-\\/#]+")
PALABRAS_OMITIBLES = {"DE", "DEL", "LA", "EL"}
# Acepta variantes: "0155-SEDE155-SAN_RAFAEL-QUEBRADONA", "sede 155 - san rafael - quebradona", "0155_SEDE_155_...".
PATRON_SEDE = re.compile(r"^(?:(\d+)[\s_\-.]*)?SEDE[\s_\-.#]*(\d+)[\s_\-.]+(.+)$")
PATRON_FECHA_CARPETA = re.compile(r"(?<!\d)(\d{2})[_\-.](\d{2})[_\-.](\d{4})(?!\d)")


def normalizar(texto: str) -> str:
    """Quita tildes, pasa a mayúsculas y unifica separadores (espacio, _, -, \\, /, #)."""
    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return SEPARADORES.sub(" ", base).strip().upper()


def clave_carpeta(nombre: str) -> str:
    """Clave para comparar nombres de carpeta: 'SOPORTE DE MEJORA' y 'SOPORTE_MEJORA' coinciden."""
    return " ".join(p for p in normalizar(nombre).split() if p not in PALABRAS_OMITIBLES)


def es_acta(nombre_archivo: str, id_sede: str, tipos: list[str], palabra: str = "ACTA") -> str | None:
    """Devuelve el tipo de acta si el archivo cumple las reglas; si no, None.

    Reglas: PDF, contiene la palabra clave (ACTA), contiene uno de los tipos permitidos
    en esa ubicación y contiene el ID de la sede como número completo.
    """
    n = normalizar(nombre_archivo)
    if not n.endswith(".PDF"):
        return None
    if not re.search(rf"\b{palabra}\b", n):
        return None
    tipo = next((t for t in tipos if re.search(rf"\b{t}\b", n)), None)
    if tipo is None:
        return None
    if not re.search(rf"(?<!\d)0*{int(id_sede)}(?!\d)", n):
        return None
    return tipo


def parsear_sede(nombre_carpeta: str) -> dict | None:
    """'0155-SEDE155-SAN_RAFAEL-QUEBRADONA' -> id 155, municipio SAN RAFAEL, nombre QUEBRADONA.

    Tolera minúsculas, tildes, espacios o _ en vez de guiones y la falta del prefijo 0155.
    'estandar' es el nombre correcto de la carpeta: NNNN-SEDENNN-MUNICIPIO-NOMBRE.
    """
    base = unicodedata.normalize("NFKD", nombre_carpeta).encode("ascii", "ignore").decode("ascii")
    m = PATRON_SEDE.match(base.strip().upper())
    if not m:
        return None
    # El guion separa municipio y nombre; sin guion no hay forma de saberlo y todo queda como municipio.
    partes = [" ".join(p.replace("_", " ").split()) for p in m.group(3).split("-", 1)]
    municipio = partes[0]
    nombre = partes[1].replace("-", " ").strip() if len(partes) > 1 else ""
    sede_id = int(m.group(2))
    id_carpeta = m.group(1) or f"{sede_id:04d}"
    estandar = f"{id_carpeta}-SEDE{sede_id}-{municipio}-{nombre}".replace(" ", "_").rstrip("-")
    return {"id": str(sede_id), "id_carpeta": id_carpeta, "municipio": municipio, "nombre": nombre,
            "estandar": estandar, "carpeta": nombre_carpeta.strip()}


def carpeta_sede(info: dict) -> str:
    """Nombre de la carpeta de salida por sede, por ejemplo 155_SAN_RAFAEL_QUEBRADONA."""
    return "_".join(f"{info['id']} {info['municipio']} {info['nombre']}".split())


def fecha_desde_nombre(nombre: str) -> dt.date | None:
    """Fecha DD-MM-YYYY dentro de un nombre de carpeta (separadores _, - o .)."""
    m = PATRON_FECHA_CARPETA.search(nombre)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def fecha_desde_cadena(nombres: tuple[str, ...]) -> dt.date | None:
    """Usa la carpeta más cercana al archivo que tenga fecha."""
    for nombre in reversed(nombres):
        f = fecha_desde_nombre(nombre)
        if f:
            return f
    return None
