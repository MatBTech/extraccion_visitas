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
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.fuentes import FuenteLocal  # noqa: E402
from core.proceso import cargar_reglas, escribir_local, procesar  # noqa: E402
from core.texto import parsear_sede  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    try:
        entrada = input("Ruta de la carpeta (ubicación con sedes o una sede): ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(1)
    ruta = Path(entrada.strip().strip('"')).expanduser()
    if not ruta.is_dir():
        print("La ruta no existe o no es una carpeta.")
        sys.exit(1)

    fuente = FuenteLocal(ruta)
    if info := parsear_sede(ruta.name):
        sedes = [(info, ruta)]
    else:
        try:
            sedes = [(i, p) for p in sorted(ruta.iterdir()) if p.is_dir() and (i := parsear_sede(p.name))]
        except OSError as e:
            print(f"No se pudo leer la carpeta: {e}")
            sys.exit(1)

    if not sedes:
        # El ID de la sede sale del nombre de la carpeta; sin él no se pueden reconocer las actas.
        print("No encontré carpetas con formato NNNN-SEDENNN-MUNICIPIO-NOMBRE.")
        sys.exit(1)
    for (info, r) in sedes:
        if info["estandar"] != r.name:
            print(f"  Nombre no estándar: '{r.name}' -> se procesa como '{info['estandar']}'")
    print(f"Sedes a procesar: {len(sedes)}")

    try:
        reglas = cargar_reglas(RAIZ / "reglas.json")
    except ValueError as e:
        print(f"Error en las reglas: {e}")
        sys.exit(1)

    print("\nProcesando...")
    try:
        resultados = procesar(fuente, sedes, reglas)
    except KeyboardInterrupt:
        print("\nCancelado; no se escribió nada.")
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
        except OSError as e:
            errores_escritura[r.info["id"]] = f"no se pudo escribir en {ruta_sede}: {e}"

    print("\nResumen:")
    for r in resultados:
        if r.error:
            print(f"  ID {r.info['id']}: ERROR - {r.error}")
        elif r.info["id"] in errores_escritura:
            print(f"  ID {r.info['id']}: ERROR - {errores_escritura[r.info['id']]}")
        else:
            print(f"  ID {r.info['id']}: {len(r.filas)} actas encontradas")
    print(f"\nResultados en la carpeta {carpeta} de cada sede.")
    if errores_escritura or any(r.error for r in resultados):
        sys.exit(1)


if __name__ == "__main__":
    main()
