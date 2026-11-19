# Extracción de actas (sedes)

Dos formas de uso que comparten el mismo núcleo (`core/`):

- **Local** (`local/extraer_local.py`): lee carpetas del PC y genera un ZIP por sede.
- **Web** (`web/app.py`): inicia sesión con Microsoft, recibe un enlace de SharePoint de solo vista y devuelve un ZIP.

## Instalación

```bash
pip install -r requirements.txt
```

Para el OCR (PDF escaneados) instala **Tesseract** en el equipo con el paquete de idioma español (`spa`).

## Local

```bash
python local/extraer_local.py
```

Pide la ruta, procesa todas las sedes encontradas (o la sede, si la ruta ya es una) y escribe dentro de cada sede una carpeta `EXTRACCION_ACTAS` con todas sus actas juntas y sin comprimir, renombradas como `TIPO_ID_DD-MM-YYYY.pdf` (por ejemplo `VISITA_155_01-06-2026.pdf`). Si dos actas coinciden en nombre se añade `_2`, `_3`…

## Web

1. En Entra ID (Azure Portal) registra una aplicación:
   - Tipo de cuenta: cuentas de la organización.
   - Plataforma **Web**, URI de redirección `http://localhost:5000/callback` (o la de tu servidor).
   - Permiso delegado de Microsoft Graph: `Files.Read.All`.
   - Crea un secreto de cliente.
   - Si la organización exige consentimiento de administrador, pídelo.
2. Exporta las variables:

```bash
export FLASK_SECRET_KEY="cambia-esto"
export GRAPH_CLIENT_ID="..."
export GRAPH_CLIENT_SECRET="..."
export GRAPH_TENANT_ID="..."          # opcional
export GRAPH_REDIRECT_URI="http://localhost:5000/callback"
python web/app.py
```

3. Abre `http://localhost:5000`, inicia sesión y pega el enlace de solo vista.

La web solo lee: no escribe ni modifica nada en SharePoint.

## Reglas de identificación

Están en `reglas.json`, sin tocar el código:

- `ubicaciones`: rutas dentro de la sede (`DESPUES/5_DOCUMENTOS`, `SOPORTE DE MEJORA`, `SOPORTE TECNICO`), si se busca de forma recursiva y qué tipos de acta se aceptan en cada una.
- Un archivo es acta si es PDF, contiene `ACTA`, contiene uno de los tipos permitidos y contiene el ID de la sede como número completo.

## Fechas

1. Fecha en el nombre de la carpeta (DD-MM-YYYY) o, si no hay, en el nombre del archivo.
2. Texto del PDF (fecha de visita, del acta, de entrega, "en la ciudad de…", 01/06/2026, 2026-06-01, "marzo 15 de 2026").
3. Si el texto no tiene fecha, OCR en español.
4. Último recurso: fecha de creación guardada en el PDF (`PDF_METADATOS`, confianza BAJA, queda en `REVISAR`).
5. Si no hay ninguna, el archivo se conserva como `FECHA_PENDIENTE` y queda en `REVISAR`.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Pendientes y advertencias

- **Vista únicamente:** si SharePoint bloquea la descarga para ese enlace, la web podrá listar carpetas pero no leer los PDF. Hay que probarlo con el enlace real antes de confiar en el resultado.
- La versión web no se ha probado contra un tenant real; la local sí se probó con datos de prueba.
- El token de la web se guarda en memoria. Para uso compartido hay que añadir almacenamiento persistente y HTTPS.
