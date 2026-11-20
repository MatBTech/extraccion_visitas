"""Pruebas del núcleo. Se ejecutan sin SharePoint y sin PyMuPDF (los PDF de prueba son falsos
a propósito, así se prueba el respaldo por nombre de carpeta)."""
import datetime as dt
import io
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.equipos import (cambios_desde_observaciones, comparar, equipos_desde_texto, excel_bytes, excel_consolidado,  # noqa: E402
                          informe_bytes, observaciones_desde_texto, seguir_cambios)
from core.fechas import extraer_fecha_pdf, fecha_desde_texto  # noqa: E402
from core.fuentes import FuenteLocal  # noqa: E402
from core.proceso import cargar_reglas, escribir_local, procesar  # noqa: E402
from core.texto import carpeta_sede, es_acta, fecha_desde_nombre, parsear_sede  # noqa: E402

REGLAS = cargar_reglas(RAIZ / "reglas.json")

# Fragmentos reales (sede 155): alcance con texto digital y entrega leída por OCR.
ALCANCE = """CONTRATO 24IA151F1473 DE 2024 - 2026 FECHA
06/02/2026 con su serial (si aplica): Nombre Marca (Si Aplica) Serial (Si Aplica) Cantidad
Equipo última milla (Kit) Starlink KIT402343891FKJ 1 Gabinete 5UR N/A N/A 1
Router Mikrotik HF509772NNG/337/r4 1 Punto PoE N/A G1T04HB002526 1 Punto PoE N/A G1T04HB002547 1
Punto PoE AP Indoor Cambium W4ZC0LWHTZVQ 1 AP Outdoor Cambium WBBH01CZQ0BZ 1 DPS clase 2 N/A N/A 1
UPS interactiva 750VA Forza/Powest E2404073229 1 Acta de Alcance - Contrato 24IA151F1473 Página 1
NOMBRE DE LA RED (Interna): GOBANT  OBSERVACIONES: sale W4ZC0LWHTZVQ entra WBBH01CZQ0BZ"""
ENTREGA = """Nombres y Seriales de los dispositivos instalados;
NOMBRE SERIAL
SERIAL -APOUTDOOR_. |W4ZCOLWHTZVQ
CAMBIUMNETWORKS_
XV2-21X
SERIAL_APINDOOR_CAMBIUM | W6YJOC8S556M
NETWORKS_XV2-21X
Instalación de internet con red Wifi - Contrato 24IA151F1473 — 2024-2026 Página 1
CONTRATO 241A151F1473 DE 2024 - 2026
POE1_CHANNELWELLTECHNO | G1T04HB002547
SERIAL_MIKROTIK_RB750Gr3 | HF509772NNG/337/R4
SERIAL _KIT_SATELITAL_STAR | KIT402343891FKJ
LINK
SERIAL_UPS_EPCOM E2404073229
NOMBRE DE LA RED (Interna): GOBANT"""


class TestEquipos(unittest.TestCase):
    def test_tabla_del_alcance(self):
        filas = equipos_desde_texto(ALCANCE, REGLAS)
        self.assertEqual([(f["Nombre"], f["Marca"], f["Serial"]) for f in filas], [
            ("Equipo última milla (Kit)", "Starlink", "KIT402343891FKJ"),
            ("Router", "Mikrotik", "HF509772NNG/337/R4"),
            ("Punto PoE", "N/A", "G1T04HB002526"),
            ("Punto PoE", "N/A", "G1T04HB002547"),
            ("AP Indoor", "Cambium", "W4ZC0LWHTZVQ"),
            ("AP Outdoor", "Cambium", "WBBH01CZQ0BZ"),
            ("UPS interactiva 750VA", "Forza/Powest", "E2404073229"),
        ])

    def test_nombres_compuestos_de_la_entrega(self):
        filas = {f["Serial"]: (f["Nombre"], f["Marca"]) for f in equipos_desde_texto(ENTREGA, REGLAS)}
        self.assertEqual(filas["W4ZCOLWHTZVQ"], ("AP Outdoor", "Cambium"))
        self.assertEqual(filas["W6YJOC8S556M"], ("AP Indoor", "Cambium"))
        self.assertEqual(filas["KIT402343891FKJ"], ("Equipo última milla (Kit)", "Starlink"))
        self.assertEqual(filas["E2404073229"], ("UPS interactiva 750VA", "Epcom"))
        self.assertNotIn("241A151F1473", filas)  # el contrato no es un serial

    def test_conserva_la_mas_reciente_e_informa_la_anterior(self):
        alcance = {"archivo": "A.pdf", "tipo": "ALCANCE", "fecha": dt.date(2026, 2, 6),
                   "equipos": equipos_desde_texto(ALCANCE, REGLAS)}
        entrega = {"archivo": "E.pdf", "tipo": "ENTREGA", "fecha": dt.date(2025, 6, 24),
                   "equipos": equipos_desde_texto(ENTREGA, REGLAS)}
        actual, cambios = comparar([entrega, alcance])
        self.assertIs(actual, alcance)
        detalles = [c["Detalle"] for c in cambios]
        # El cruce es por serial: POE1 de la entrega es el segundo Punto PoE del alcance.
        self.assertIn("Punto PoE G1T04HB002547 (POE1_CHANNELWELLTECHNO en la entrega).", detalles)
        self.assertIn("W4ZCOLWHTZVQ era el AP Outdoor en la entrega y en el alcance figura como AP Indoor.",
                      detalles)  # O/0 del OCR
        self.assertIn("W6YJOC8S556M (AP Indoor de la entrega) no aparece en el alcance.", detalles)
        self.assertIn("WBBH01CZQ0BZ es un AP Outdoor nuevo en el alcance.", detalles)

    def test_excel_con_fuente_y_fecha(self):
        from openpyxl import load_workbook

        alcance = {"archivo": "A.pdf", "tipo": "ALCANCE", "fecha": dt.date(2026, 2, 6),
                   "equipos": equipos_desde_texto(ALCANCE, REGLAS)}
        actual, cambios = comparar([alcance])
        self.assertEqual(cambios, [])
        sede = parsear_sede("0155-SEDE155-SAN_RAFAEL-QUEBRADONA")
        libro = load_workbook(io.BytesIO(excel_bytes(sede, actual)))
        filas = list(libro["Equipos"].iter_rows(values_only=True))
        self.assertEqual(filas[0], ("ID", "Carpeta", "Fuente", "Fecha", "Nombre", "Marca", "Serial", "Serial vigente"))
        self.assertEqual(filas[1], ("155", "0155-SEDE155-SAN_RAFAEL-QUEBRADONA", "ALCANCE", "06-02-2026",
                                    "Equipo última milla (Kit)", "Starlink", "KIT402343891FKJ", "KIT402343891FKJ"))
        self.assertEqual(len(filas), 8)
        # Sin soportes, la hoja Final lista igual todos los equipos, sin cambios.
        final = list(libro["Final"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(final), 7)
        self.assertTrue(all(f[7] == "Sin cambios" and f[12] == "OK" for f in final))
        # Con una sola acta el informe se crea igual, indicando que no hay comparación.
        self.assertIn("no hay otra con qué comparar", informe_bytes("155", actual, cambios).decode("utf-8-sig"))

    def test_informe_agrupa_los_cambios(self):
        alcance = {"archivo": "A.pdf", "tipo": "ALCANCE", "fecha": dt.date(2026, 2, 6),
                   "equipos": equipos_desde_texto(ALCANCE, REGLAS)}
        entrega = {"archivo": "E.pdf", "tipo": "ENTREGA", "fecha": dt.date(2025, 6, 24),
                   "equipos": equipos_desde_texto(ENTREGA, REGLAS)}
        texto = informe_bytes("155", *comparar([entrega, alcance])).decode("utf-8-sig")
        self.assertIn("Comparación con el acta anterior: ENTREGA del 24-06-2025 (E.pdf)", texto)
        self.assertIn("Cambian de nombre:\r\n    - W4ZCOLWHTZVQ era el AP Outdoor", texto)

    def test_fecha_tras_encabezado_de_contrato(self):
        self.assertEqual(fecha_desde_texto(ALCANCE)["fecha"], dt.date(2026, 2, 6))


class TestActas(unittest.TestCase):
    def test_reconoce_variantes_de_nombre(self):
        self.assertEqual(es_acta("ACTA_ALCANCE_ID#155.pdf", "155", ["ALCANCE", "ENTREGA"]), "ALCANCE")
        self.assertEqual(es_acta("ACTA_DE_ ENTREGA_ID#155.pdf", "155", ["ALCANCE", "ENTREGA"]), "ENTREGA")
        self.assertEqual(es_acta("FORMATO ACTA_VISITA - NUEVAS CONEXIONES V4 ID155(1).pdf", "155", ["VISITA"]),
                         "VISITA")

    def test_rechaza_otros_casos(self):
        self.assertIsNone(es_acta("ACTA_ALCANCE_ID#1550.pdf", "155", ["ALCANCE"]))
        self.assertIsNone(es_acta("ACTA_VISITA_155.pdf", "155", ["ALCANCE", "ENTREGA"]))
        self.assertIsNone(es_acta("ACTA_ALCANCE_155.docx", "155", ["ALCANCE"]))
        self.assertIsNone(es_acta("otro.pdf", "155", ["ALCANCE"]))


class TestSedesYFechas(unittest.TestCase):
    def test_parsea_sede(self):
        info = parsear_sede("0155-SEDE155-SAN_RAFAEL-QUEBRADONA")
        self.assertEqual((info["id"], info["municipio"], info["nombre"]), ("155", "SAN RAFAEL", "QUEBRADONA"))
        self.assertEqual(carpeta_sede(info), "155_SAN_RAFAEL_QUEBRADONA")
        self.assertIsNone(parsear_sede("SOPORTE TECNICO"))
        self.assertEqual(info["estandar"], "0155-SEDE155-SAN_RAFAEL-QUEBRADONA")

    def test_normaliza_nombres_de_sede_no_estandar(self):
        for variante in ["0155 - Sede 155 - San_Rafael - Quebradona", "sede155-san rafael-quebradona",
                         "0155_SEDE_155-SAN__RAFAÉL-QUEBRADONA", "SEDE #155 SAN_RAFAEL-QUEBRADONA"]:
            info = parsear_sede(variante)
            self.assertIsNotNone(info, variante)
            self.assertEqual(info["estandar"], "0155-SEDE155-SAN_RAFAEL-QUEBRADONA", variante)
            self.assertEqual(carpeta_sede(info), "155_SAN_RAFAEL_QUEBRADONA", variante)
        self.assertIsNone(parsear_sede("SEDES ANTIGUAS"))

    def test_fecha_en_nombre_de_carpeta(self):
        self.assertEqual(fecha_desde_nombre("01_06_2026"), dt.date(2026, 6, 1))
        self.assertEqual(fecha_desde_nombre("02-09-2026"), dt.date(2026, 9, 2))
        self.assertEqual(fecha_desde_nombre("06.02.2026"), dt.date(2026, 2, 6))
        self.assertIsNone(fecha_desde_nombre("SOPORTE TECNICO"))
        self.assertIsNone(fecha_desde_nombre("31_02_2026"))

    def test_fecha_del_texto_ignora_vencimientos(self):
        r = fecha_desde_texto("Fecha de visita: 01/06/2026. Vencimiento: 01/06/2028")
        self.assertEqual(r["fecha"], dt.date(2026, 6, 1))
        self.assertEqual(r["confianza"], "ALTA")

    def test_fecha_formato_en_la_ciudad_de(self):
        r = fecha_desde_texto("En la ciudad de Bogotá, a los 5 días del mes de junio de 2026")
        self.assertEqual(r["fecha"], dt.date(2026, 6, 5))
        self.assertEqual(r["confianza"], "ALTA")

    def test_fecha_y_hora_del_formato_de_entrega(self):
        # Formato real de "ACTA DE ENTREGA": la fecha va después del rótulo "FECHA Y HORA"
        r = fecha_desde_texto("FECHA Y HORA 24/06/2025 04:00 PM MUNICIPIO SAN RAFAEL (ORIENTE)")
        self.assertEqual(r["fecha"], dt.date(2025, 6, 24))
        self.assertEqual(r["confianza"], "ALTA")

    def test_formatos_iso_y_mes_primero(self):
        self.assertEqual(fecha_desde_texto("Fecha de visita: 2026-06-01")["fecha"], dt.date(2026, 6, 1))
        self.assertEqual(fecha_desde_texto("Medellín, marzo 15 de 2024")["fecha"], dt.date(2024, 3, 15))

    def test_pdf_sin_fecha_en_texto_usa_metadatos(self):
        import fitz

        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Acta de visita sin fecha escrita en el cuerpo del documento.")
        doc.set_metadata({"creationDate": "D:20250310120000"})
        r = extraer_fecha_pdf(doc.tobytes(), usar_ocr=False)
        self.assertEqual((r["fecha"], r["fuente"], r["confianza"]), (dt.date(2025, 3, 10), "PDF_METADATOS", "BAJA"))

    def test_sin_fecha(self):
        self.assertIsNone(fecha_desde_texto("texto sin fechas"))

    def test_nombre_real_de_acta_de_entrega(self):
        self.assertEqual(es_acta("ACTA_DE__ENTREGA_ID155.pdf", "155", ["ALCANCE", "ENTREGA"]), "ENTREGA")


class TestProcesoLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        sede = self.tmp / "0155-SEDE155-SAN_RAFAEL-QUEBRADONA"
        (sede / "DESPUES" / "5_DOCUMENTOS").mkdir(parents=True)
        (sede / "SOPORTE DE MEJORA").mkdir(parents=True)
        (sede / "SOPORTE TECNICO" / "01_06_2026").mkdir(parents=True)
        (sede / "SOPORTE TECNICO" / "02-09-2026").mkdir(parents=True)
        (sede / "DESPUES" / "5_DOCUMENTOS" / "ACTA_ALCANCE_ID#155.pdf").write_bytes(b"%PDF-falso A")
        (sede / "DESPUES" / "5_DOCUMENTOS" / "ACTA_DE_ ENTREGA_ID#155.pdf").write_bytes(b"%PDF-falso B")
        (sede / "SOPORTE DE MEJORA" / "ACTA_ENTREGA_ID155.pdf").write_bytes(b"%PDF-falso A")  # duplicado
        (sede / "SOPORTE TECNICO" / "01_06_2026" / "ACTA_VISITA_155 (1).pdf").write_bytes(b"%PDF-falso C")
        (sede / "SOPORTE TECNICO" / "02-09-2026" / "FORMATO ACTA_VISITA V4 ID155.pdf").write_bytes(b"%PDF-falso D")
        (sede / "SOPORTE TECNICO" / "02-09-2026" / "otro.pdf").write_bytes(b"x")
        (sede / "SOPORTE TECNICO" / "02-09-2026" / "ACTA_VISITA_1550.pdf").write_bytes(b"x")
        self.sede = sede

    def test_procesa_sede(self):
        info = parsear_sede(self.sede.name)
        (res,) = procesar(FuenteLocal(self.tmp), [(info, self.sede)], REGLAS)
        self.assertIsNone(res.error)

        por_original = {f["NOMBRE_ORIGINAL"]: f for f in res.filas}
        self.assertNotIn("otro.pdf", por_original)
        self.assertNotIn("ACTA_VISITA_1550.pdf", por_original)
        self.assertIn("FORMATO ACTA_VISITA V4 ID155.pdf", por_original)

        # Sin fecha en carpeta ni PDF legible: queda como FECHA_PENDIENTE
        self.assertEqual(por_original["ACTA_ALCANCE_ID#155.pdf"]["NOMBRE_NORMALIZADO"],
                         "ALCANCE_155_QUEBRADONA_FECHA_PENDIENTE.pdf")
        # Fecha tomada de la carpeta 01_06_2026
        self.assertEqual(por_original["ACTA_VISITA_155 (1).pdf"]["NOMBRE_NORMALIZADO"],
                         "VISITA_155_QUEBRADONA_01-06-2026.pdf")
        self.assertEqual(por_original["ACTA_VISITA_155 (1).pdf"]["FUENTE_FECHA"], "CARPETA")
        # Mismo contenido que otra acta: se marca como duplicado y no se copia
        self.assertEqual(por_original["ACTA_ENTREGA_ID155.pdf"]["ESTADO"], "DUPLICADO")

    def test_actas_juntas_sin_comprimir(self):
        info = parsear_sede(self.sede.name)
        (res,) = procesar(FuenteLocal(self.tmp), [(info, self.sede)], REGLAS)
        salida = self.sede / "EXTRACCION_ACTAS"
        escribir_local(res, salida)
        nombres = {f.name for f in salida.iterdir()}
        self.assertIn("VISITA_155_QUEBRADONA_01-06-2026.pdf", nombres)
        self.assertIn("ALCANCE_155_QUEBRADONA_FECHA_PENDIENTE.pdf", nombres)
        self.assertTrue(all(f.is_file() and f.suffix == ".pdf" for f in salida.iterdir()))

    def test_error_en_una_ubicacion_no_pierde_las_demas(self):
        class FuenteRota(FuenteLocal):
            def hijos_archivos(self, ref):
                if ref.name == "SOPORTE DE MEJORA":
                    raise PermissionError("acceso denegado")
                return super().hijos_archivos(ref)

        info = parsear_sede(self.sede.name)
        (res,) = procesar(FuenteRota(self.tmp), [(info, self.sede)], REGLAS)
        self.assertIsNone(res.error)
        self.assertTrue(any("PermissionError: acceso denegado" in linea for linea in res.log))
        originales = {f["NOMBRE_ORIGINAL"] for f in res.filas}
        self.assertIn("ACTA_VISITA_155 (1).pdf", originales)  # SOPORTE TECNICO sí se procesó

    def test_reglas_invalidas_dan_mensaje_claro(self):
        mala = self.tmp / "reglas.json"
        mala.write_text('{"palabra_acta": "ACTA", "ubicaciones": [{"salida": "X"}]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ubicación #1 no tiene ruta"):
            cargar_reglas(mala)
        mala.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no es JSON válido"):
            cargar_reglas(mala)


# Observaciones reales de las visitas de soporte técnico de la sede 155.
VISITA_01_06 = """CONTRATO 24IA151F1473 DE 2024 - 2026
OBSERVACIONES (Letra Legible):
Se realiza visita técnica a la sede, donde se evidencia que el equipo Outdoor llevaba
varios días inoperativo. Durante la inspección se identifica daño en el POE con serial
G1T04HB002526, el cual es reemplazado por el POE con serial
N000900L017B2213003016.
Adicionalmente, se verifica que el equipo Outdoor se encuentra quemado (serial
WBBH01CZQ0BZ), por lo que se procede a instalar un nuevo equipo Outdoor con serial
WBBH00TK3Q3G.
se adjunta en un anexo 1 la nueva foto
Punto PoE
N/A
G1T04HB002547
Se informa al docente acerca del servicio de Mesa de Ayuda"""
VISITA_02_09 = """OBSERVACIONES (Letra Legible):
Se realiza soporte técnico a la sede con el objetivo de restablecer completamente el
servicio de conectividad. Durante la intervención, se procede al reemplazo del Mikrotik
HF509772NNG/337/r4 por el Mikrotik HJX0AWM8JDB/r4, logrando recuperar la
operación de la infraestructura de red."""
VISITA_04_11 = """OBSERVACIONES (Letra Legible):
reemplazo del equipo Mikrotik quemado, con la siguiente novedad:
•
Mikrotik retirado: HJX0AWM8JDB/r4.
•
Mikrotik instalado: HKF0AXDRQ9H/r4.
Posteriormente, se realizan las validaciones de los equipos conectados, identificando
que el AP Outdoor se encuentra quemado, por lo cual se procede a su reemplazo:
•
AP Outdoor retirado: WBBM0322FZ9H.
•
AP Outdoor instalado: WBCA05QRCH4L.
Acta de Alcance - Contrato 24IA151F1473 – 2024-2026 Página 3"""


def _cambios(texto):
    return [(c["Equipo"], c["Serial retirado"], c["Serial instalado"])
            for c in cambios_desde_observaciones(observaciones_desde_texto(texto), REGLAS)]


class TestObservaciones(unittest.TestCase):
    def test_sale_entra(self):
        self.assertEqual(_cambios(ALCANCE), [("", "W4ZC0LWHTZVQ", "WBBH01CZQ0BZ")])

    def test_reemplazado_por_e_instalar_nuevo(self):
        # El serial de la tabla tras las observaciones (G1T04HB002547) no es un cambio.
        self.assertEqual(_cambios(VISITA_01_06), [("Punto PoE", "G1T04HB002526", "N000900L017B2213003016"),
                                                  ("AP Outdoor", "WBBH01CZQ0BZ", "WBBH00TK3Q3G")])

    def test_reemplazo_del_x_por_el_y(self):
        self.assertEqual(_cambios(VISITA_02_09), [("Router", "HF509772NNG/337/R4", "HJX0AWM8JDB/R4")])

    def test_retirado_instalado(self):
        self.assertEqual(_cambios(VISITA_04_11), [("Router", "HJX0AWM8JDB/R4", "HKF0AXDRQ9H/R4"),
                                                  ("AP Outdoor", "WBBM0322FZ9H", "WBCA05QRCH4L")])

    def test_sin_observaciones(self):
        self.assertIsNone(observaciones_desde_texto("ACTA DE VISITA sin esa sección"))

    def test_orden_cronologico_verifica_y_da_serial_vigente(self):
        from openpyxl import load_workbook

        alcance = {"archivo": "A.pdf", "tipo": "ALCANCE", "fecha": dt.date(2026, 2, 6),
                   "equipos": equipos_desde_texto(ALCANCE, REGLAS)}
        cambios = []
        obs_alcance = "OBSERVACIONES: Cambio de AP OUTDOOR sale W4ZC0LWHTZVQ entra WBBH01CZQ0BZ"  # texto real
        for fecha, texto in [(dt.date(2026, 2, 6), obs_alcance), (dt.date(2026, 6, 1), VISITA_01_06),
                             (dt.date(2026, 9, 2), VISITA_02_09), (dt.date(2026, 11, 4), VISITA_04_11)]:
            for c in cambios_desde_observaciones(observaciones_desde_texto(texto), REGLAS):
                cambios.append({**c, "Fecha": fecha, "Acta": f"V_{fecha:%m}.pdf", "Soporte": "SOPORTE_TECNICO"})
        seguir_cambios([alcance], cambios)
        self.assertEqual([c["Verificación"] for c in cambios][:5], ["OK"] * 5)
        # El Outdoor retirado el 04/11 nunca figuró instalado: falta un acta intermedia.
        self.assertIn("no figura instalado antes", cambios[5]["Verificación"])

        libro = load_workbook(io.BytesIO(excel_bytes(parsear_sede("0155-SEDE155-SAN_RAFAEL-QUEBRADONA"),
                                                     alcance, cambios, [])))
        equipos = {f[4] + f[6]: f[7] for f in libro["Equipos"].iter_rows(min_row=2, values_only=True)}
        self.assertEqual(equipos["RouterHF509772NNG/337/R4"], "HKF0AXDRQ9H/R4")  # dos cambios seguidos
        self.assertEqual(equipos["AP OutdoorWBBH01CZQ0BZ"], "WBBH00TK3Q3G")
        self.assertEqual(equipos["AP IndoorW4ZC0LWHTZVQ"], "W4ZC0LWHTZVQ")  # sin cambios: el mismo
        self.assertEqual(len(list(libro["Cambios de serial"].iter_rows())), 7)

        # Final: ID, Carpeta, Equipo, Marca, Acta base, Serial original, Serial actual, Estado, N°, ...
        final = {(f[2], f[5]): f for f in libro["Final"].iter_rows(min_row=2, values_only=True)}
        outdoor = final[("AP Outdoor", "W4ZC0LWHTZVQ")]  # la historia empieza antes del acta base
        self.assertEqual((outdoor[6], outdoor[7]), ("WBBH00TK3Q3G", "Cambió 2 veces"))
        self.assertEqual(final[("Router", "HF509772NNG/337/R4")][6:9], ("HKF0AXDRQ9H/R4", "Cambió 2 veces", 2))
        self.assertEqual(final[("UPS interactiva 750VA", "E2404073229")][7], "Sin cambios")
        suelto = final[("AP Outdoor", "WBBM0322FZ9H")]  # cambio sin equipo del acta que lo explique
        self.assertEqual((suelto[4], suelto[6]), ("No está en el acta base", "WBCA05QRCH4L"))
        self.assertTrue(suelto[12].startswith("REVISAR"))

        # Consolidado: una sede con cambios y otra sin ellos; las hojas se apilan con un solo encabezado.
        otra = excel_bytes(parsear_sede("0200-SEDE200-ANDES-CENTRO"), alcance, [], [])
        global_ = load_workbook(io.BytesIO(excel_consolidado([otra, excel_bytes(
            parsear_sede("0155-SEDE155-SAN_RAFAEL-QUEBRADONA"), alcance, cambios, [])])))
        self.assertEqual(global_.sheetnames[0], "Final")
        ids = [f[0] for f in global_["Final"].iter_rows(min_row=2, values_only=True)]
        self.assertEqual(len(ids), ids.count("200") + len(final))
        self.assertTrue(ids.count("200"))
        self.assertEqual(ids[0], "200")
        self.assertEqual(ids[-1], "155")
        self.assertEqual(len(list(global_["Cambios de serial"].iter_rows())), 7)


if __name__ == "__main__":
    unittest.main()
