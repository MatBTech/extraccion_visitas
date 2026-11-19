"""Procesa sedes: localiza actas, obtiene fechas, copia y arma ZIP e inventarios.

No sabe si los datos vienen de disco o de SharePoint; eso lo decide la fuente.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .fechas import extraer_fecha_pdf
from .texto import carpeta_sede, clave_carpeta, es_acta, fecha_desde_cadena

log = logging.getLogger("actas")

COLUMNAS = ["ID_SEDE", "NOMBRE_SEDE", "MUNICIPIO", "TIPO_SOPORTE", "TIPO_ACTA", "NOMBRE_ORIGINAL",
            "NOMBRE_NORMALIZADO", "FECHA_ACTA", "FRAGMENTO_FECHA", "CONFIANZA_FECHA", "FUENTE_FECHA",
            "FECHA_CARPETA", "CONFLICTO_FECHA", "RUTA_ORIGEN", "ESTADO", "OBSERVACIONES", "HASH_SHA256"]


@dataclass
class ResultadoSede:
    info: dict
    filas: list[dict] = field(default_factory=list)
    archivos: list[tuple[str, bytes]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    error: str | None = None

    def registrar(self, mensaje: str) -> None:
        linea = f"[{self.info.get('id', '?')}] {mensaje}"
        self.log.append(linea)
        log.info(linea)


def cargar_reglas(ruta) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _buscar_hijo(fuente, ref, segmento: str):
    objetivo = clave_carpeta(segmento)
    for nombre, r in fuente.hijos_carpetas(ref):
        if clave_carpeta(nombre) == objetivo:
            return r
    return None


def _recorrer(fuente, ref, recursivo: bool, cadena: tuple[str, ...] = ()):
    for nombre, r in fuente.hijos_archivos(ref):
        yield nombre, r, cadena
    if recursivo:
        for nombre, r in fuente.hijos_carpetas(ref):
            yield from _recorrer(fuente, r, True, cadena + (nombre,))


def _nombre_salida(tipo: str, id_sede: str, fecha, usados: set[str]) -> str:
    sufijo = fecha.strftime("%d-%m-%Y") if fecha else "FECHA_PENDIENTE"
    base = f"{tipo}_{id_sede}_{sufijo}"
    nombre, n = f"{base}.pdf", 2
    while nombre in usados:
        nombre = f"{base}_{n}.pdf"
        n += 1
    usados.add(nombre)
    return nombre


def _txt_fecha(f) -> str:
    return f.strftime("%d-%m-%Y") if f else ""


def _procesar_acta(fuente, aref, nombre, tipo, ub, info, cadena, carpeta, hashes, usados, res) -> dict:
    fila = {c: "" for c in COLUMNAS}
    fila.update(ID_SEDE=info["id"], NOMBRE_SEDE=info["nombre"], MUNICIPIO=info["municipio"],
                TIPO_SOPORTE=ub["salida"], TIPO_ACTA=tipo, NOMBRE_ORIGINAL=nombre,
                RUTA_ORIGEN=fuente.ruta(aref))
    try:
        data = fuente.leer(aref)
    except Exception as e:  # noqa: BLE001 - se registra y se sigue con las demás
        fila.update(ESTADO="FALLO_DESCARGA", OBSERVACIONES=f"descarga fallida: {e}")
        res.registrar(f"fallo de descarga: {nombre}")
        return fila

    sha = hashlib.sha256(data).hexdigest()
    fila["HASH_SHA256"] = sha
    obs: list[str] = []
    estado = "OK"

    pdf = None
    try:
        pdf = extraer_fecha_pdf(data)
        if pdf is None:
            obs.append("PDF sin fecha identificable")
    except Exception as e:  # noqa: BLE001
        estado = "PDF_NO_ABRE"
        obs.append(f"no se pudo leer el PDF: {e}")

    fecha_carp = fecha_desde_cadena(cadena)
    fecha, fuente_f, conf, frag, conflicto = None, "", "", "", "NO"

    if pdf:
        fecha, fuente_f, conf, frag = pdf["fecha"], pdf["fuente"], pdf["confianza"], pdf["fragmento"]
        if conf == "BAJA":
            estado = "REVISAR"
            obs.append("fecha de baja confianza en el PDF")
        if fecha_carp and fecha_carp != fecha:
            conflicto = "SI"
            estado = "REVISAR"
            obs.append(f"la carpeta indica {_txt_fecha(fecha_carp)}")
    elif fecha_carp:
        fecha, fuente_f, conf = fecha_carp, "CARPETA", "MEDIA"
        obs.append("fecha tomada del nombre de la carpeta")

    if fecha is None:
        estado = "REVISAR"
        obs.append("fecha no identificada: FECHA_PENDIENTE")

    if sha in hashes:
        estado = "DUPLICADO"
        obs.append(f"idéntico a {hashes[sha]}")
        nombre_salida = ""
    else:
        nombre_salida = _nombre_salida(tipo, info["id"], fecha, usados)
        hashes[sha] = f"{ub['salida']}/{nombre_salida}"
        res.archivos.append((f"{carpeta}/{ub['salida']}/{nombre_salida}", data))

    fila.update(NOMBRE_NORMALIZADO=nombre_salida, FECHA_ACTA=_txt_fecha(fecha) or "FECHA_PENDIENTE",
                FRAGMENTO_FECHA=frag, CONFIANZA_FECHA=conf, FUENTE_FECHA=fuente_f,
                FECHA_CARPETA=_txt_fecha(fecha_carp), CONFLICTO_FECHA=conflicto,
                ESTADO=estado, OBSERVACIONES="; ".join(obs))
    res.registrar(f"{nombre} -> {nombre_salida or 'duplicado'} ({estado})")
    return fila


def procesar_sede(fuente, ref, info: dict, reglas: dict) -> ResultadoSede:
    res = ResultadoSede(info=info)
    carpeta = carpeta_sede(info)
    hashes: dict[str, str] = {}

    for ub in reglas["ubicaciones"]:
        ref_ub = ref
        for segmento in ub["ruta"]:
            if ref_ub is None:
                break
            ref_ub = _buscar_hijo(fuente, ref_ub, segmento)
        if ref_ub is None:
            res.registrar(f"ubicación no encontrada: {ub['salida']}")
            continue

        usados: set[str] = set()
        for nombre, aref, cadena in _recorrer(fuente, ref_ub, ub["recursivo"]):
            tipo = es_acta(nombre, info["id"], ub["tipos"], reglas["palabra_acta"])
            if tipo is None:
                continue
            res.filas.append(_procesar_acta(fuente, aref, nombre, tipo, ub, info,
                                            cadena, carpeta, hashes, usados, res))

    res.archivos.append((f"{carpeta}/INVENTARIO_SEDE.csv", csv_bytes(res.filas)))
    return res


def procesar(fuente, sedes: list[tuple[dict, object]], reglas: dict) -> list[ResultadoSede]:
    """Procesa cada sede por separado; un error en una no detiene a las demás."""
    resultados = []
    for info, ref in sedes:
        try:
            resultados.append(procesar_sede(fuente, ref, info, reglas))
        except Exception as e:  # noqa: BLE001
            r = ResultadoSede(info=info, error=str(e))
            r.registrar(f"error en la sede: {e}")
            resultados.append(r)
    return resultados


def csv_bytes(filas: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(filas)
    return buf.getvalue().encode("utf-8-sig")


def reporte_general(resultados: list[ResultadoSede]) -> bytes:
    return csv_bytes([f for r in resultados for f in r.filas])


def log_texto(resultados: list[ResultadoSede]) -> bytes:
    return "\n".join(linea for r in resultados for linea in r.log).encode("utf-8")


def zip_sede(res: ResultadoSede) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta, datos in res.archivos:
            z.writestr(ruta, datos)
    return buf.getvalue()


def zip_global(resultados: list[ResultadoSede]) -> bytes:
    """Un ZIP con un ZIP por sede, más el reporte general y el log (para la web)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in resultados:
            if not r.error:
                z.writestr(f"{carpeta_sede(r.info)}.zip", zip_sede(r))
        z.writestr("REPORTE_GENERAL.csv", reporte_general(resultados))
        z.writestr("LOG_EJECUCION.log", log_texto(resultados))
    return buf.getvalue()


def escribir_local(resultados: list[ResultadoSede], salida: Path) -> None:
    """Escribe en disco un ZIP por sede, el reporte general y el log (para la versión local)."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    for r in resultados:
        if not r.error:
            (salida / f"{carpeta_sede(r.info)}.zip").write_bytes(zip_sede(r))
    (salida / "REPORTE_GENERAL.csv").write_bytes(reporte_general(resultados))
    (salida / "LOG_EJECUCION.log").write_bytes(log_texto(resultados))
