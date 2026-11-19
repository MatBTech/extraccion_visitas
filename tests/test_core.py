"""Pruebas del núcleo. Se ejecutan sin SharePoint y sin PyMuPDF (los PDF de prueba son falsos
a propósito, así se prueba el respaldo por nombre de carpeta)."""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.fechas import extraer_fecha_pdf, fecha_desde_texto  # noqa: E402
from core.fuentes import FuenteLocal  # noqa: E402
from core.proceso import cargar_reglas, escribir_local, procesar  # noqa: E402
from core.texto import carpeta_sede, es_acta, fecha_desde_nombre, parsear_sede  # noqa: E402

REGLAS = cargar_reglas(RAIZ / "reglas.json")


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
