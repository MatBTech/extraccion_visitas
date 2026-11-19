#!/usr/bin/env python3
"""Extracción local de actas desde carpetas del PC.

Uso:
    python local/extraer_local.py
Pide una ruta (ubicación con varias sedes, o una sede), procesa todas las sedes
y deja en cada sede una carpeta EXTRACCION_ACTAS_<DD-MM-YYYY_HH-MM-SS> con las actas renombradas,
el Excel de equipos y el informe de cambios.
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

log = logging.getLogger("actas")


def configurar_logging() -> Path:
    """Consola: INFO (lo esencial). Archivo logs/extraccion_FECHA.log: DEBUG (todo el detalle + trazas)."""
    carpeta = RAIZ / "logs"
    carpeta.mkdir(exist_ok=True)
    archivo = carpeta / f"extraccion_{dt.datetime.now():%Y%m%d_%H%M%S}.log"

    consola = logging.StreamHandler()
    consola.setLevel(logging.INFO)
    consola.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))

    en_archivo = logging.FileHandler(archivo, encoding="utf-8")
    en_archivo.setLevel(logging.DEBUG)
    en_archivo.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(module)s:%(lineno)d] %(message)s"))

    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG)
    raiz.addHandler(consola)
    raiz.addHandler(en_archivo)
    # Librerías ruidosas en DEBUG (PIL, urllib3...) solo desde WARNING.
    for nombre in ("PIL", "urllib3", "pytesseract"):
        logging.getLogger(nombre).setLevel(logging.WARNING)

    # Cualquier error no capturado queda en el archivo con su traza completa.
    def _no_capturada(tipo, valor, traza):
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, traza)
            return
        log.critical("Error no controlado", exc_info=(tipo, valor, traza))
    sys.excepthook = _no_capturada
    return archivo


def main() -> None:
    archivo_log = configurar_logging()
    inicio = time.perf_counter()
    log.info("Inicio. Log detallado en: %s", archivo_log)
    log.debug("Python %s | ejecutable %s", sys.version.split()[0], sys.executable)
    # Se importan aquí para que una dependencia faltante quede registrada en el log.
    from core.fuentes import FuenteLocal
    from core.proceso import cargar_reglas, escribir_local, procesar
    from core.texto import parsear_sede

    try:
        entrada = input("Ruta de la carpeta (ubicación con sedes o una sede): ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(1)
    ruta = Path(entrada.strip().strip('"')).expanduser()
    log.info("Ruta ingresada: %s", ruta)
    if not ruta.is_dir():
        log.error("La ruta no existe o no es una carpeta: %s", ruta)
        print("La ruta no existe o no es una carpeta.")
        sys.exit(1)

    fuente = FuenteLocal(ruta)
    if info := parsear_sede(ruta.name):
        sedes = [(info, ruta)]
    else:
        try:
            sedes = [(i, p) for p in sorted(ruta.iterdir()) if p.is_dir() and (i := parsear_sede(p.name))]
        except OSError as e:
            log.exception("No se pudo listar %s", ruta)
            print(f"No se pudo leer la carpeta: {e}")
            sys.exit(1)

    if not sedes:
        # El ID de la sede sale del nombre de la carpeta; sin él no se pueden reconocer las actas.
        log.error("Sin sedes válidas en %s", ruta)
        print("No encontré carpetas con formato NNNN-SEDENNN-MUNICIPIO-NOMBRE.")
        sys.exit(1)
    for (info, r) in sedes:
        if info["estandar"] != r.name:
            log.warning("Nombre no estándar: '%s' -> se procesa como '%s'", r.name, info["estandar"])
    log.info("Sedes a procesar: %d", len(sedes))

    try:
        reglas = cargar_reglas(RAIZ / "reglas.json")
    except ValueError as e:
        log.error("Error en las reglas: %s", e)
        sys.exit(1)

    log.info("Reglas cargadas: %d ubicaciones", len(reglas["ubicaciones"]))
    log.info("Procesando...")
    try:
        resultados = procesar(fuente, sedes, reglas)
    except KeyboardInterrupt:
        log.warning("Cancelado por el usuario; no se escribió nada.")
        sys.exit(130)

    # Una carpeta nueva por extracción: las anteriores quedan como historial y nada se sobrescribe.
    carpeta = f"EXTRACCION_ACTAS_{dt.datetime.now():%d-%m-%Y_%H-%M-%S}"
    errores_escritura = {}
    for (_, ruta_sede), r in zip(sedes, resultados):
        if r.error:
            continue
        # Una sede bloqueada (archivo abierto, OneDrive, permisos) no impide escribir las demás.
        try:
            escribir_local(r, ruta_sede / carpeta)
            log.debug("Escritos %d archivos en %s", len(r.archivos), ruta_sede / carpeta)
        except OSError as e:
            log.exception("No se pudo escribir la sede %s", r.info["id"])
            errores_escritura[r.info["id"]] = f"no se pudo escribir en {ruta_sede}: {e}"

    print("\nResumen:")
    for r in resultados:
        if r.error:
            print(f"  ID {r.info['id']}: ERROR - {r.error}")
        elif r.info["id"] in errores_escritura:
            print(f"  ID {r.info['id']}: ERROR - {errores_escritura[r.info['id']]}")
        else:
            avisos = sum(1 for linea in r.log if "ERROR en la ubicación" in linea)
            extra = f" ({avisos} ubicaciones con error, ver {archivo_log.name})" if avisos else ""
            print(f"  ID {r.info['id']}: {len(r.filas)} actas encontradas{extra}")
    print(f"\nResultados en la carpeta {carpeta} de cada sede.")
    hubo_error = bool(errores_escritura or any(r.error for r in resultados))
    log.info("Fin en %.1f s. Sedes: %d, actas: %d, con error: %s. Log: %s",
             time.perf_counter() - inicio, len(resultados), sum(len(r.filas) for r in resultados),
             "SÍ" if hubo_error else "no", archivo_log)
    if hubo_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
