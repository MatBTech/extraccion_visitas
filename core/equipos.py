"""Equipos con serial de las actas de ALCANCE y ENTREGA de una sede.

Toma la tabla de equipos de cada acta, relaciona los nombres por palabras clave
('AP Outdoor' en el alcance = 'SERIAL_APOUTDOOR_CAMBIUMNETWORKS' en la entrega),
conserva el acta más reciente y compara contra ella las más antiguas.
El cruce entre actas se hace por serial, no por la posición en la tabla.

Además lee las OBSERVACIONES de las actas de soporte (técnico / de mejora) en orden de fecha
y saca los equipos a los que se les cambió el serial (sale X, entra Y).
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


# --- Cambios de serial descritos en OBSERVACIONES (actas de soporte técnico / de mejora) ---

INICIO_OBS = re.compile(r"OBSERVACIONES\s*(?:\(\s*LETRA\s+LEGIBLE\s*\))?\s*:?", re.IGNORECASE)
FIN_OBS = re.compile(r"SOPORTES\s+DE\s+LA\s+INSTALACI|SE\s+INFORMA\s+AL\s+DOCENTE|L[IÍ]NEA\s+DE\s+ATENCI"
                     r"|ACTA\s+DE\s+ALCANCE\s*-\s*CONTRATO|NOTA\s*:", re.IGNORECASE)
# Palabras justo antes de un serial que dicen si ese equipo sale o entra. Gana la más cercana al serial.
SALE = {"SALE", "RETIRADO", "RETIRADA", "RETIRA", "RETIRO", "DANO", "DANADO", "DANADA", "QUEMADO", "QUEMADA",
        "AVERIADO", "AVERIADA", "REEMPLAZO", "REEMPLAZA", "ANTERIOR"}
ENTRA = {"ENTRA", "INSTALADO", "INSTALADA", "INSTALA", "INSTALAR", "INSTALO", "NUEVO", "POR"}
VENTANA_OBS = 12  # palabras antes del serial que se revisan


def observaciones_desde_texto(texto: str) -> str | None:
    """Texto de la sección OBSERVACIONES del acta (None si el acta no la tiene)."""
    ini = INICIO_OBS.search(texto)
    if not ini:
        return None
    fin = FIN_OBS.search(texto, ini.end())
    return " ".join(texto[ini.end():fin.start() if fin else len(texto)].split())


def cambios_desde_observaciones(obs: str, reglas: dict) -> list[dict]:
    """[{'Equipo', 'Serial retirado', 'Serial instalado'}] según lo que digan las observaciones.

    'sale X entra Y', 'reemplazo del Mikrotik X por el Mikrotik Y', 'Mikrotik retirado: X. Mikrotik instalado: Y',
    'daño en el POE con serial X, reemplazado por el POE con serial Y'...
    """
    tokens = [t.strip(".,;:()[]\"'•") for t in obs.split()]
    seriales, previo = [], 0
    for i, t in enumerate(tokens):
        if not _es_serial(t, set()):
            continue
        contexto = [_clave(p) for p in tokens[max(previo, i - VENTANA_OBS):i]]
        previo = i + 1
        sentido = next((s for p in reversed(contexto) for s, pal in (("sale", SALE), ("entra", ENTRA)) if p in pal), None)
        if sentido:  # un serial sin palabra que lo explique (p. ej. una tabla tras las observaciones) se ignora
            equipo = _ultima_clave("".join(contexto), reglas["equipos"], "claves")[0]
            seriales.append((sentido, t.upper(), equipo["nombre"] if equipo else ""))

    # Cada serial que sale se empareja con el siguiente que entra (del mismo equipo si se puede).
    cambios, pendientes = [], []
    for sentido, serial, equipo in seriales:
        if sentido == "sale":
            pendientes.append({"Equipo": equipo, "Serial retirado": serial, "Serial instalado": ""})
            continue
        par = next((p for p in pendientes if equipo and p["Equipo"] == equipo), pendientes[0] if pendientes else None)
        if par:
            pendientes.remove(par)
            par.update({"Serial instalado": serial, "Equipo": par["Equipo"] or equipo})
            cambios.append(par)
        else:
            cambios.append({"Equipo": equipo, "Serial retirado": "", "Serial instalado": serial})
    return cambios + pendientes


def seguir_cambios(actas: list[dict], cambios: list[dict]) -> None:
    """Recorre los cambios (ya en orden de fecha) y marca en 'Verificación' si el serial retirado era uno
    instalado antes (en un alcance/entrega anterior o en un cambio previo)."""
    conocidos = {}  # llave -> fecha en que se vio instalado por primera vez
    for a in actas:
        for e in a["equipos"]:
            k = _llave_serial(e["Serial"])
            conocidos[k] = min(conocidos.get(k, dt.date.max), a["fecha"] or dt.date.min)
    reemplazo = {}
    for c in cambios:
        ret, ins = c["Serial retirado"], c["Serial instalado"]
        notas = []
        if not ret:
            notas.append("no se indica el serial retirado")
        elif (visto := conocidos.get(_llave_serial(ret))) is None or (c["Fecha"] and visto > c["Fecha"]):
            notas.append("el serial retirado no figura instalado antes (¿falta un acta?)")
        if not ins:
            notas.append("no se indica el serial instalado")
        if not c["Equipo"]:
            notas.append("no se identificó el equipo")
        c["Verificación"] = "OK" if not notas else "REVISAR: " + "; ".join(notas)
        if ins:
            conocidos.setdefault(_llave_serial(ins), c["Fecha"] or dt.date.min)


def consolidado(actual: dict | None, cambios: list[dict]) -> list[dict]:
    """Una fila por equipo con su historia completa de seriales (cambios ya en orden de fecha).

    Parte de cada equipo del acta base (alcance/entrega más reciente), busca hacia atrás los cambios que
    lo instalaron y hacia adelante los que lo reemplazaron (X -> Y -> Z, solo del mismo equipo).
    Los cambios que no encajan con ningún equipo del acta base salen en filas propias.
    """
    usados: set[int] = set()

    def mismo(c, campo, serial, equipo):
        return bool(c[campo]) and _llave_serial(c[campo]) == _llave_serial(serial) and c["Equipo"] in ("", equipo)

    def adelante(serial, equipo, hist):
        for i, c in enumerate(cambios):
            if i not in usados and serial and mismo(c, "Serial retirado", serial, equipo):
                usados.add(i)
                hist.append(c)
                serial = c["Serial instalado"]
        return serial

    def fila(equipo, marca, base, hist, final):
        return {"Equipo": equipo, "Marca": marca, "Base": base, "Historial": hist, "Actual": final,
                "Original": hist[0]["Serial retirado"] if hist else final}

    filas = []
    for e in actual["equipos"] if actual else []:
        atras, serial = [], e["Serial"]
        while (i := next((i for i in reversed(range(len(cambios)))  # ¿qué cambio instaló este serial?
                          if i not in usados and mismo(cambios[i], "Serial instalado", serial, e["Nombre"])),
                         None)) is not None:
            usados.add(i)
            atras.insert(0, cambios[i])
            serial = cambios[i]["Serial retirado"]
        hist = atras
        final = adelante(e["Serial"], e["Nombre"], hist)
        filas.append(fila(e["Nombre"], e["Marca"], f"{actual['tipo']} {_txt(actual['fecha'])}", hist, final))
    for i, c in enumerate(cambios):
        if i not in usados:
            usados.add(i)
            hist = [c]
            final = adelante(c["Serial instalado"], c["Equipo"], hist)
            filas.append(fila(c["Equipo"], "", "No está en el acta base", hist, final))
    return filas


COLUMNAS_CAMBIOS = ["Fecha", "Acta", "Soporte", "Equipo", "Serial retirado", "Serial instalado", "Verificación"]
COLUMNAS_FINAL = ["Equipo", "Marca", "Acta base", "Serial original", "Serial actual", "Estado", "N° cambios",
                  "Último cambio", "Acta del último cambio", "Historial de seriales", "Verificación"]


def _filas_final(filas: list[dict]) -> list[list]:
    salida = []
    for f in filas:
        h = f["Historial"]
        n = len(h)
        estado = "Sin cambios" if not n else f"Cambió {n} {'vez' if n == 1 else 'veces'}"
        if h and not f["Actual"]:
            estado += " (retirado sin reemplazo)"
        historial = " | ".join(f"{_txt(c['Fecha'])}: {c['Serial retirado'] or '?'} → {c['Serial instalado'] or '?'}"
                               f" ({c['Acta']})" for c in h)
        revisar = [c["Verificación"] for c in h if c["Verificación"] != "OK"]
        salida.append([f["Equipo"], f["Marca"], f["Base"], f["Original"], f["Actual"], estado, n,
                       _txt(h[-1]["Fecha"]) if h else "", h[-1]["Acta"] if h else "", historial,
                       "; ".join(revisar) if revisar else "OK"])
    return salida


def _hoja(libro, titulo: str, columnas: list[str], filas: list[list], primera: bool = False):
    from openpyxl.styles import Alignment, Font

    hoja = libro.active if primera else libro.create_sheet()
    hoja.title = titulo
    hoja.append(columnas)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in filas:
        hoja.append(fila)
    for col in hoja.columns:
        ancho = max(len(str(c.value or "")) for c in col) + 2
        hoja.column_dimensions[col[0].column_letter].width = min(ancho, 80)
        if ancho > 80:
            for c in col[1:]:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    hoja.freeze_panes = "A2"


def excel_bytes(sede: dict, actual: dict | None, cambios: list[dict] = (), observaciones: list[dict] = ()) -> bytes:
    """Hojas, todas con ID y Carpeta de la sede al inicio:
    'Final' (cada equipo con su serial original, actual e historial completo; también los que no cambian),
    'Equipos' (acta de alcance/entrega más reciente, con el serial vigente tras los soportes),
    'Cambios de serial' (en orden de fecha) y 'Observaciones' (texto de cada acta de soporte)."""
    from openpyxl import Workbook

    pre = [sede["id"], sede.get("carpeta", sede.get("estandar", ""))]
    cols = ["ID", "Carpeta"]
    final = consolidado(actual, list(cambios))
    libro = Workbook()
    _hoja(libro, "Final", cols + COLUMNAS_FINAL, [pre + f for f in _filas_final(final)], primera=True)
    equipos = actual["equipos"] if actual else []
    _hoja(libro, "Equipos", cols + COLUMNAS_TABLA + ["Serial vigente"],
          [pre + [actual["tipo"], _txt(actual["fecha"]), e["Nombre"], e["Marca"], e["Serial"], f["Actual"]]
           for e, f in zip(equipos, final)])  # las primeras filas de 'final' son los equipos del acta, en orden
    if cambios or observaciones:
        _hoja(libro, "Cambios de serial", cols + COLUMNAS_CAMBIOS,
              [pre + [_txt(c["Fecha"]), c["Acta"], c["Soporte"], c["Equipo"], c["Serial retirado"],
                      c["Serial instalado"], c["Verificación"]] for c in cambios])
        _hoja(libro, "Observaciones", cols + ["Fecha", "Acta", "Soporte", "Cambios detectados", "Observaciones"],
              [pre + [_txt(o["Fecha"]), o["Acta"], o["Soporte"], o["Cambios"], o["Texto"]] for o in observaciones])
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
