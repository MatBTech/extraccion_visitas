"""Procesa sedes: localiza actas, obtiene fechas, copia y arma ZIP e inventarios.

No sabe si los datos vienen de disco o de SharePoint; eso lo decide la fuente.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import logging
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .equipos import (cambios_desde_observaciones, comparar, equipos_desde_texto, excel_bytes, informe_bytes,
                      observaciones_desde_texto, seguir_cambios)
from .fechas import extraer_fecha_pdf, texto_pdf
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

    def registrar(self, mensaje: str, nivel: int = logging.INFO) -> None:
        linea = f"[{self.info.get('id', '?')}] {mensaje}"
        self.log.append(linea)
        log.log(nivel, linea, stacklevel=2)  # muestra la línea que llamó, no esta


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
        res.registrar(f"fallo de descarga: {nombre} ({_err(e)})", logging.ERROR)
        return fila

    sha = hashlib.sha256(data).hexdigest()
    fila["HASH_SHA256"] = sha
    obs: list[str] = []
    estado = "OK"

    # Orden: carpeta -> nombre del archivo -> contenido del PDF (texto, OCR, metadatos).
    fecha_carp = fecha_desde_cadena(cadena) or fecha_desde_nombre(nombre)
    fecha, fuente_f, conf, frag, conflicto = None, "", "", "", "NO"

    log.debug("[%s] acta %s (%s, %d bytes) en %s", info["id"], nombre, tipo, len(data), fila["RUTA_ORIGEN"])
    if fecha_carp:
        fecha, fuente_f, conf = fecha_carp, "CARPETA", "ALTA"
    else:
        try:
            pdf = extraer_fecha_pdf(data)
        except Exception as e:  # noqa: BLE001
            pdf = None
            estado = "PDF_NO_ABRE"
            obs.append(f"no se pudo leer el PDF: {_err(e)}")
            res.registrar(f"PDF ilegible: {nombre} ({_err(e)})", logging.WARNING)
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
    log.debug("[%s] fecha=%s fuente=%s confianza=%s fragmento=%r", info["id"], _txt_fecha(fecha) or "-",
              fuente_f or "-", conf or "-", frag)
    res.registrar(f"{nombre} -> {nombre_salida or 'duplicado'} ({estado})",
                  logging.INFO if estado in ("OK", "DUPLICADO") else logging.WARNING)
    return fila


SOPORTES = ("SOPORTE_TECNICO", "SOPORTE_MEJORA")


def _fecha_fila(f: dict):
    return None if f["FECHA_ACTA"] == "FECHA_PENDIENTE" else dt.datetime.strptime(f["FECHA_ACTA"], "%d-%m-%Y").date()


def _tablas_equipos(res: ResultadoSede, reglas: dict) -> list[tuple[str, bytes]]:
    """EQUIPOS_<id>.xlsx (equipos del alcance/entrega más reciente + cambios de serial de los soportes)
    e INFORME_<id>.txt (cambios frente a las actas anteriores)."""
    datos = dict(res.archivos)
    textos: dict[str, str | None] = {}

    def texto(f: dict) -> str | None:
        archivo = f["NOMBRE_NORMALIZADO"]
        if archivo not in textos:  # una sola lectura (y OCR) por acta
            try:
                textos[archivo] = texto_pdf(datos[archivo])
            except Exception as e:  # noqa: BLE001
                res.registrar(f"no se pudo leer el texto de {archivo}: {_err(e)}", logging.WARNING)
                textos[archivo] = None
        return textos[archivo]

    filas = [f for f in res.filas if f["NOMBRE_NORMALIZADO"]]  # sin duplicados ni fallos de lectura
    actas = []
    for f in filas:
        if f["TIPO_ACTA"] not in ("ALCANCE", "ENTREGA") or (t := texto(f)) is None:
            continue
        lista = equipos_desde_texto(t, reglas)
        if not lista:
            res.registrar(f"sin equipos con serial en {f['NOMBRE_NORMALIZADO']}")
            continue
        actas.append({"archivo": f["NOMBRE_NORMALIZADO"], "tipo": f["TIPO_ACTA"], "fecha": _fecha_fila(f),
                      "equipos": lista})

    # Un acta en soporte idéntica a otra (p. ej. el alcance copiado de DESPUES) se marca DUPLICADO y no se
    # copia; igual se leen sus observaciones, desde la fila del archivo que sí se copió.
    original = {f["HASH_SHA256"]: f for f in filas}
    soportes = list({o["NOMBRE_NORMALIZADO"]: {**o, "TIPO_SOPORTE": f["TIPO_SOPORTE"]} for f in res.filas
                     if f["TIPO_SOPORTE"] in SOPORTES and (o := original.get(f["HASH_SHA256"]))}.values())
    # De la más antigua a la más reciente (sin fecha al final): cada cambio parte del anterior.
    soportes.sort(key=lambda f: (_fecha_fila(f) is None, _fecha_fila(f) or dt.date.min, f["NOMBRE_NORMALIZADO"]))
    cambios_serial, observaciones = [], []
    for f in soportes:
        archivo, fecha = f["NOMBRE_NORMALIZADO"], _fecha_fila(f)
        if (t := texto(f)) is None:
            continue
        obs = observaciones_desde_texto(t)
        if obs is None:
            res.registrar(f"sin sección OBSERVACIONES en {archivo} (¿PDF escaneado sin OCR?)", logging.WARNING)
            continue
        cambios = cambios_desde_observaciones(obs, reglas)
        for c in cambios:
            c.update(Fecha=fecha, Acta=archivo, Soporte=f["TIPO_SOPORTE"])
            log.info("[%s] %s %s: %s %s -> %s", res.info["id"], _txt_fecha(fecha) or "sin fecha", archivo,
                     c["Equipo"] or "?", c["Serial retirado"] or "?", c["Serial instalado"] or "?")
        cambios_serial += cambios
        observaciones.append({"Fecha": fecha, "Acta": archivo, "Soporte": f["TIPO_SOPORTE"], "Texto": obs,
                              "Cambios": len(cambios)})
        log.debug("[%s] observaciones de %s: %s", res.info["id"], archivo, obs)

    if not actas and not observaciones:
        return []
    seguir_cambios(actas, cambios_serial)
    for c in cambios_serial:
        if c["Verificación"] != "OK":
            res.registrar(f"cambio de serial a revisar en {c['Acta']}: {c['Verificación']}", logging.WARNING)
    res.registrar(f"{len(cambios_serial)} cambios de serial en {len(observaciones)} actas de soporte")

    actual, cambios = comparar(actas) if actas else (None, [])
    salida = [(f"EQUIPOS_{res.info['id']}.xlsx", excel_bytes(res.info, actual, cambios_serial, observaciones))]
    if actual:
        salida.append((f"INFORME_{res.info['id']}.txt", informe_bytes(res.info["id"], actual, cambios)))
    return salida


def procesar_sede(fuente, ref, info: dict, reglas: dict) -> ResultadoSede:
    res = ResultadoSede(info=info)
    inicio = time.perf_counter()
    log.info("=== Sede %s (%s) ===", info.get("id", "?"), info.get("nombre", ""))
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
                res.registrar(f"ubicación no encontrada: {ub['salida']} (ruta {ub['ruta']})", logging.WARNING)
                continue

            for nombre, aref, cadena in _recorrer(fuente, ref_ub, ub["recursivo"]):
                tipo = es_acta(nombre, info["id"], ub["tipos"], reglas["palabra_acta"])
                if tipo is None:
                    continue
                res.filas.append(_procesar_acta(fuente, aref, nombre, tipo, ub, info,
                                                cadena, hashes, usados, res))
        except Exception as e:  # noqa: BLE001
            log.exception("error en la ubicación %s", ub["salida"])
            res.registrar(f"ERROR en la ubicación {ub['salida']} (resultados parciales): {_err(e)}",
                          logging.ERROR)

    if reglas.get("equipos"):
        res.archivos += _tablas_equipos(res, reglas)

    log.info("[%s] %d actas en %.1f s", info.get("id", "?"), len(res.filas), time.perf_counter() - inicio)
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
            r.registrar(f"ERROR en la sede: {_err(e)}", logging.ERROR)
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


# def zip_global(resultados: list[ResultadoSede]) -> bytes:
#     """Un ZIP con un ZIP por sede, más el reporte general y el log (para la web)."""
#     buf = io.BytesIO()
#     with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
#         for r in resultados:
#             if not r.error:
#                 z.writestr(f"{carpeta_sede(r.info)}.zip", zip_sede(r))
#         z.writestr("REPORTE_GENERAL.csv", reporte_general(resultados))
#         z.writestr("LOG_EJECUCION.log", log_texto(resultados))
#     return buf.getvalue()


def escribir_local(res: ResultadoSede, salida: Path) -> None:
    """Copia las actas de una sede, sin comprimir, en la carpeta de salida (versión local)."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    for nombre, datos in res.archivos:
        (salida / nombre).write_bytes(datos)
