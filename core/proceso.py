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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .fechas import extraer_fecha_pdf
from .texto import carpeta_sede, clave_carpeta, es_acta, fecha_desde_cadena, fecha_desde_nombre

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


def _err(e: Exception) -> str:
    """Mensaje legible que incluye el tipo (un KeyError solo mostraría la clave)."""
    return f"{type(e).__name__}: {e}"


def cargar_reglas(ruta) -> dict:
    """Lee reglas.json y valida su estructura para fallar con un mensaje claro y no a mitad de proceso."""
    try:
        reglas = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"No se pudo leer {ruta}: {_err(e)}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"{ruta} no es JSON válido (línea {e.lineno}, columna {e.colno}): {e.msg}") from e
    if not isinstance(reglas.get("palabra_acta"), str) or not isinstance(reglas.get("ubicaciones"), list):
        raise ValueError(f"{ruta}: faltan 'palabra_acta' (texto) o 'ubicaciones' (lista).")
    for i, ub in enumerate(reglas["ubicaciones"]):
        faltan = [k for k in ("salida", "ruta", "recursivo", "tipos") if k not in ub]
        if faltan:
            raise ValueError(f"{ruta}: la ubicación #{i + 1} no tiene {', '.join(faltan)}.")
    return reglas


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


def _procesar_acta(fuente, aref, nombre, tipo, ub, info, cadena, hashes, usados, res) -> dict:
    fila = {c: "" for c in COLUMNAS}
    fila.update(ID_SEDE=info["id"], NOMBRE_SEDE=info["nombre"], MUNICIPIO=info["municipio"],
                TIPO_SOPORTE=ub["salida"], TIPO_ACTA=tipo, NOMBRE_ORIGINAL=nombre,
                RUTA_ORIGEN=fuente.ruta(aref))
    try:
        data = fuente.leer(aref)
    except Exception as e:  # noqa: BLE001 - se registra y se sigue con las demás
        fila.update(ESTADO="FALLO_DESCARGA", OBSERVACIONES=f"descarga fallida: {_err(e)}")
        res.registrar(f"fallo de descarga: {nombre} ({_err(e)})")
        return fila

    sha = hashlib.sha256(data).hexdigest()
    fila["HASH_SHA256"] = sha
    obs: list[str] = []
    estado = "OK"

    # Orden: carpeta -> nombre del archivo -> contenido del PDF (texto, OCR, metadatos).
    fecha_carp = fecha_desde_cadena(cadena) or fecha_desde_nombre(nombre)
    fecha, fuente_f, conf, frag, conflicto = None, "", "", "", "NO"

    if fecha_carp:
        fecha, fuente_f, conf = fecha_carp, "CARPETA", "ALTA"
    else:
        try:
            pdf = extraer_fecha_pdf(data)
        except Exception as e:  # noqa: BLE001
            pdf = None
            estado = "PDF_NO_ABRE"
            obs.append(f"no se pudo leer el PDF: {_err(e)}")
            res.registrar(f"PDF ilegible: {nombre} ({_err(e)})")
        if pdf:
            fecha, fuente_f, conf, frag = pdf["fecha"], pdf["fuente"], pdf["confianza"], pdf["fragmento"]
            if conf == "BAJA":
                estado = "REVISAR"
                obs.append(f"fecha de baja confianza ({fuente_f})")

    if fecha is None:
        estado = "REVISAR"
        obs.append("fecha no identificada: FECHA_PENDIENTE")

    if sha in hashes:
        estado = "DUPLICADO"
        obs.append(f"idéntico a {hashes[sha]}")
        nombre_salida = ""
    else:
        nombre_salida = _nombre_salida(tipo, info["id"], fecha, usados)
        hashes[sha] = nombre_salida
        res.archivos.append((nombre_salida, data))

    fila.update(NOMBRE_NORMALIZADO=nombre_salida, FECHA_ACTA=_txt_fecha(fecha) or "FECHA_PENDIENTE",
                FRAGMENTO_FECHA=frag, CONFIANZA_FECHA=conf, FUENTE_FECHA=fuente_f,
                FECHA_CARPETA=_txt_fecha(fecha_carp), CONFLICTO_FECHA=conflicto,
                ESTADO=estado, OBSERVACIONES="; ".join(obs))
    res.registrar(f"{nombre} -> {nombre_salida or 'duplicado'} ({estado})")
    return fila


def procesar_sede(fuente, ref, info: dict, reglas: dict) -> ResultadoSede:
    res = ResultadoSede(info=info)
    hashes: dict[str, str] = {}
    usados: set[str] = set()  # por sede: todas las actas van juntas en la misma carpeta

    for ub in reglas["ubicaciones"]:
        # Un error al listar una ubicación (permisos, red) no descarta lo ya hallado en las demás.
        try:
            ref_ub = ref
            for segmento in ub["ruta"]:
                if ref_ub is None:
                    break
                ref_ub = _buscar_hijo(fuente, ref_ub, segmento)
            if ref_ub is None:
                res.registrar(f"ubicación no encontrada: {ub['salida']}")
                continue

            for nombre, aref, cadena in _recorrer(fuente, ref_ub, ub["recursivo"]):
                tipo = es_acta(nombre, info["id"], ub["tipos"], reglas["palabra_acta"])
                if tipo is None:
                    continue
                res.filas.append(_procesar_acta(fuente, aref, nombre, tipo, ub, info,
                                                cadena, hashes, usados, res))
        except Exception as e:  # noqa: BLE001
            log.exception("error en la ubicación %s", ub["salida"])
            res.registrar(f"ERROR en la ubicación {ub['salida']} (resultados parciales): {_err(e)}")

    return res


def procesar(fuente, sedes: Sequence[tuple[dict, object]], reglas: dict) -> list[ResultadoSede]:
    """Procesa cada sede por separado; un error en una no detiene a las demás."""
    resultados = []
    for info, ref in sedes:
        try:
            resultados.append(procesar_sede(fuente, ref, info, reglas))
        except Exception as e:  # noqa: BLE001
            log.exception("error en la sede %s", info.get("id", "?"))
            r = ResultadoSede(info=info, error=_err(e))
            r.registrar(f"ERROR en la sede: {_err(e)}")
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


def escribir_local(res: ResultadoSede, salida: Path) -> None:
    """Copia las actas de una sede, sin comprimir, en la carpeta de salida (versión local)."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    for nombre, datos in res.archivos:
        (salida / nombre).write_bytes(datos)
