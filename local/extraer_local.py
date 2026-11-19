#!/usr/bin/env python3
"""Extracción local de actas desde carpetas del PC.

Uso:
    python local/extraer_local.py
Pide una ruta (ubicación con varias sedes, o una sede), procesa todas las sedes
y deja en cada sede una carpeta EXTRACCION_ACTAS con las actas renombradas, sin comprimir.
"""
from __future__ import annotations

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

    ruta = Path(input("Ruta de la carpeta (ubicación con sedes o una sede): ").strip().strip('"')).expanduser()
    if not ruta.is_dir():
        print("La ruta no existe o no es una carpeta.")
        sys.exit(1)

    fuente = FuenteLocal(ruta)
    if parsear_sede(ruta.name):
        candidatas = [(ruta.name, ruta)]
    else:
        candidatas = [(p.name, p) for p in sorted(ruta.iterdir()) if p.is_dir() and parsear_sede(p.name)]

    if not candidatas:
        # El ID de la sede sale del nombre de la carpeta; sin él no se pueden reconocer las actas.
        print("No encontré carpetas con formato NNNN-SEDENNN-MUNICIPIO-NOMBRE.")
        sys.exit(1)
    sedes = [(parsear_sede(n), r) for n, r in candidatas]
    print(f"Sedes a procesar: {len(sedes)}")

    reglas = cargar_reglas(RAIZ / "reglas.json")

    print("\nProcesando...")
    resultados = procesar(fuente, sedes, reglas)
    for (_, ruta_sede), r in zip(sedes, resultados):
        if not r.error:
            escribir_local(r, ruta_sede / "EXTRACCION_ACTAS")

    print("\nResumen:")
    for r in resultados:
        if r.error:
            print(f"  ID {r.info['id']}: ERROR - {r.error}")
        else:
            print(f"  ID {r.info['id']}: {len(r.filas)} actas encontradas")
    print("\nResultados en la carpeta EXTRACCION_ACTAS de cada sede.")


if __name__ == "__main__":
    main()
