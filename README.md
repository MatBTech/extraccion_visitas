# Extracción de actas (sedes)

Dos formas de uso que comparten el mismo núcleo (`core/`):

- **Local** (`local/extraer_local.py`): lee carpetas del PC y genera un ZIP por sede.

## Instalación

```bash
pip install -r requirements.txt
```

Para el OCR (PDF escaneados) instala **Tesseract** en el equipo con el paquete de idioma español (`spa`).

## Local

```bash
python local/extraer_local.py
```

Pide la ruta, procesa todas las sedes encontradas (o la sede, si la ruta ya es una) y escribe dentro de cada sede una carpeta `EXTRACCION_ACTAS` con:

- `NNN_MUNICIPIO_NOMBRE.zip` por sede (con `INVENTARIO_SEDE.csv` dentro).
- `REPORTE_GENERAL.csv` (separado por `;`, UTF-8 con BOM para Excel).
- `LOG_EJECUCION.log`.

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

1. Texto del PDF (fecha de visita, del acta, de entrega, o "en la ciudad de…, a los… días del mes de…").
2. Si el PDF no tiene texto, OCR en español.
3. Si no hay fecha en el PDF, la fecha de la carpeta (formato DD-MM-YYYY).
4. Si la carpeta y el PDF no coinciden, se usa el PDF y se marca `CONFLICTO_FECHA = SI`.
5. Si no hay ninguna, el archivo se conserva como `FECHA_PENDIENTE` y queda en `REVISAR`.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Pendientes y advertencias

- **Vista únicamente:** si SharePoint bloquea la descarga para ese enlace, la web podrá listar carpetas pero no leer los PDF. Hay que probarlo con el enlace real antes de confiar en el resultado.
- La versión web no se ha probado contra un tenant real; la local sí se probó con datos de prueba.
- El token de la web se guarda en memoria. Para uso compartido hay que añadir almacenamiento persistente y HTTPS.
