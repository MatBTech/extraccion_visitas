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

from core.equipos import comparar, equipos_desde_texto, excel_bytes, informe_bytes  # noqa: E402
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
        filas = list(load_workbook(io.BytesIO(excel_bytes(actual)))["Equipos"].iter_rows(values_only=True))
        self.assertEqual(filas[0], ("Fuente", "Fecha", "Nombre", "Marca", "Serial"))
        self.assertEqual(filas[1], ("ALCANCE", "06-02-2026", "Equipo última milla (Kit)", "Starlink", "KIT402343891FKJ"))
        self.assertEqual(len(filas), 8)
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
                         "ALCANCE_155_FECHA_PENDIENTE.pdf")
        # Fecha tomada de la carpeta 01_06_2026
        self.assertEqual(por_original["ACTA_VISITA_155 (1).pdf"]["NOMBRE_NORMALIZADO"],
                         "VISITA_155_01-06-2026.pdf")
        self.assertEqual(por_original["ACTA_VISITA_155 (1).pdf"]["FUENTE_FECHA"], "CARPETA")
        # Mismo contenido que otra acta: se marca como duplicado y no se copia
        self.assertEqual(por_original["ACTA_ENTREGA_ID155.pdf"]["ESTADO"], "DUPLICADO")

    def test_actas_juntas_sin_comprimir(self):
        info = parsear_sede(self.sede.name)
        (res,) = procesar(FuenteLocal(self.tmp), [(info, self.sede)], REGLAS)
        salida = self.sede / "EXTRACCION_ACTAS"
        escribir_local(res, salida)
        nombres = {f.name for f in salida.iterdir()}
        self.assertIn("VISITA_155_01-06-2026.pdf", nombres)
        self.assertIn("ALCANCE_155_FECHA_PENDIENTE.pdf", nombres)
        self.assertTrue(all(f.is_file() and f.suffix == ".pdf" for f in salida.iterdir()))


if __name__ == "__main__":
    unittest.main()
