"""Equipos con serial de las actas de ALCANCE y ENTREGA de una sede.

Toma la tabla de equipos de cada acta, relaciona los nombres por palabras clave
('AP Outdoor' en el alcance = 'SERIAL_APOUTDOOR_CAMBIUMNETWORKS' en la entrega),
conserva el acta más reciente y compara contra ella las más antiguas.
El cruce entre actas se hace por serial, no por la posición en la tabla.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import unicodedata

INICIO = re.compile(r"SERIAL", re.IGNORECASE)            # la tabla va tras la primera mención de "serial"
FIN = re.compile(r"NOMBRE\s+DE\s+LA\s+RED", re.IGNORECASE)
COLUMNAS_TABLA = ["Fuente", "Fecha", "Nombre", "Marca", "Serial"]
TITULOS = {"Coincide": "Coinciden", "Cambia de nombre": "Cambian de nombre",
           "No aparece": "No aparecen en el acta actual", "Nuevo": "Nuevos en el acta actual"}


def _clave(texto: str) -> str:
    """'AP Outdoor' y 'SERIAL_APOUTDOOR_' -> 'APOUTDOOR' / 'SERIALAPOUTDOOR'."""
    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]", "", base.upper())


def _llave_serial(serial: str) -> str:
    # El OCR confunde O/0 e I/1: se comparan como iguales.
    return serial.upper().replace("O", "0").replace("I", "1")


def _es_serial(token: str, excluir: set[str]) -> bool:
    t = token.upper()
    return (len(t) >= 8 and bool(re.fullmatch(r"[A-Z0-9/\-]+", t)) and bool(re.search(r"[A-Z]", t))
            and bool(re.search(r"\d", t)) and t not in excluir)


def _ultima_clave(texto: str, opciones: list[dict], campo: str):
    """(opción, clave) cuya clave aparece más tarde en el texto (la más cercana al serial)."""
    mejor, clave, pos = None, None, -1
    for op in opciones:
        for c in op[campo]:
            p = texto.rfind(c)
            if p > pos:
                mejor, clave, pos = op, c, p
    return mejor, clave


def equipos_desde_texto(texto: str, reglas: dict) -> list[dict]:
    """Filas Nombre/Marca/Serial/Original de los equipos con serial del acta."""
    ini = INICIO.search(texto)
    if not ini:
        return []
    fin = FIN.search(texto, ini.end())
    seccion = texto[ini.end():fin.start() if fin else len(texto)].replace("|", " ")
    # El número de contrato del encabezado de cada página parece un serial.
    excluir = {c.upper() for c in re.findall(r"CONTRATO\s+(\S+)", texto, re.IGNORECASE)}
    tokens = [t.strip(".,;:()[]\"'") for t in seccion.split()]
    indices = [i for i, t in enumerate(tokens) if _es_serial(t, excluir)]
    marcas = [{"marca": m, "claves": [k]} for k, m in reglas["marcas"].items()]

    filas, previo = [], 0
    for n, i in enumerate(indices):
        siguiente = indices[n + 1] if n + 1 < len(indices) else len(tokens)
        fila_tokens = tokens[previo:i]
        antes = _clave("".join(fila_tokens))
        despues = _clave("".join(tokens[i + 1:siguiente]))
        previo = i + 1
        equipo, clave = _ultima_clave(antes, reglas["equipos"], "claves")
        if equipo is None:
            continue
        # Tras el serial solo vale lo que va antes del siguiente equipo (p. ej. "STAR" | "LINK" partido por el OCR).
        corte = min([p for op in reglas["equipos"] for c in op["claves"] if (p := despues.find(c)) >= 0],
                    default=len(despues))
        marca = (_ultima_clave(antes, marcas, "claves")[0]
                 or _ultima_clave(antes + despues[:corte], marcas, "claves")[0])
        # Nombre tal cual en el acta (p. ej. POE1_CHANNELWELLTECHNO) para ver el cruce.
        original = next((t.strip("_-.") for t in reversed(fila_tokens) if clave in _clave(t)), equipo["nombre"])
        filas.append({"Nombre": equipo["nombre"], "Marca": marca["marca"] if marca else "N/A",
                      "Serial": tokens[i].upper(), "Original": original})
    return filas


def comparar(actas: list[dict]) -> tuple[dict, list[dict]]:
    """actas: [{'archivo', 'tipo', 'fecha', 'equipos'}]. Devuelve (acta más reciente, cambios frente a las anteriores)."""
    orden = sorted(actas, key=lambda a: a["fecha"] or dt.date.min, reverse=True)
    actual = orden[0]
    por_serial = {_llave_serial(e["Serial"]): e for e in actual["equipos"]}
    ta = actual["tipo"].lower()
    cambios = []
    for vieja in orden[1:]:
        tv = vieja["tipo"].lower()
        base = {"Acta anterior": f"{vieja['tipo']} del {_txt(vieja['fecha'])} ({vieja['archivo']})"}
        vistos = set()
        for e in vieja["equipos"]:
            k = _llave_serial(e["Serial"])
            vistos.add(k)
            a = por_serial.get(k)
            if a is None:
                res, det = "No aparece", f"{e['Serial']} ({e['Nombre']} de la {tv}) no aparece en el {ta}."
            elif a["Nombre"] != e["Nombre"]:
                res, det = ("Cambia de nombre",
                            f"{e['Serial']} era el {e['Nombre']} en la {tv} y en el {ta} figura como {a['Nombre']}.")
            else:
                res, det = "Coincide", f"{a['Nombre']} {a['Serial']} ({e['Original']} en la {tv})."
            if a is not None and a["Marca"] != e["Marca"] and e["Marca"] != "N/A" and a["Marca"] != "N/A":
                det += f" Marca: {e['Marca']} en la {tv}, {a['Marca']} en el {ta}."
            cambios.append({**base, "Resultado": res, "Detalle": det})
        for k, a in por_serial.items():
            if k not in vistos:
                cambios.append({**base, "Resultado": "Nuevo",
                                "Detalle": f"{a['Serial']} es un {a['Nombre']} nuevo en el {ta}."})
    orden_res = {"Coincide": 0, "Cambia de nombre": 1, "No aparece": 2, "Nuevo": 3}
    cambios.sort(key=lambda c: (c["Acta anterior"], orden_res[c["Resultado"]]))
    return actual, cambios


def _txt(f) -> str:
    return f.strftime("%d-%m-%Y") if f else "FECHA_PENDIENTE"


def excel_bytes(actual: dict) -> bytes:
    """Hoja 'Equipos': Fuente (ALCANCE/ENTREGA), Fecha, Nombre, Marca y Serial del acta más reciente."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Equipos"
    hoja.append(COLUMNAS_TABLA)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for e in actual["equipos"]:
        hoja.append([actual["tipo"], _txt(actual["fecha"]), e["Nombre"], e["Marca"], e["Serial"]])
    for col in hoja.columns:
        hoja.column_dimensions[col[0].column_letter].width = max(len(str(c.value)) for c in col) + 2
    hoja.freeze_panes = "A2"
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


def informe_bytes(id_sede: str, actual: dict, cambios: list[dict]) -> bytes:
    """Informe en texto de lo que cambia entre el acta más reciente y las anteriores."""
    lineas = [f"INFORME DE EQUIPOS - SEDE {id_sede}",
              f"Acta actual (fuente del Excel): {actual['tipo']} del {_txt(actual['fecha'])} ({actual['archivo']})", ""]
    if not cambios:
        lineas.append("Solo hay un acta de alcance/entrega: no hay otra con qué comparar.")
    for anterior in dict.fromkeys(c["Acta anterior"] for c in cambios):
        lineas.append(f"Comparación con el acta anterior: {anterior}")
        for res, titulo in TITULOS.items():
            detalles = [c["Detalle"] for c in cambios if c["Acta anterior"] == anterior and c["Resultado"] == res]
            if detalles:
                lineas.append(f"  {titulo}:")
                lineas += [f"    - {d}" for d in detalles]
        lineas.append("")
    return ("\r\n".join(lineas) + "\r\n").encode("utf-8-sig")  # BOM y CRLF: se abre bien en el Bloc de notas
