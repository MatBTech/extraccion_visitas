# Extracción de actas (sedes)

Lee las carpetas de las sedes en el PC, encuentra las actas (alcance, entrega, visita), las renombra con su fecha y genera por sede un Excel de equipos y un informe de cambios. El núcleo está en `core/` y el punto de entrada es `local/extraer_local.py`.

## Requisitos

- Windows 10 o 11 con conexión a internet la primera vez.
- Nada más: `file.bat` instala lo que falte.

## Instalación

**Automática (recomendada):** copia la carpeta del proyecto y haz doble clic en `file.bat`. En la primera ejecución:

1. Si no hay Python 3.10 o superior, instala Python 3.13 para el usuario con `winget` (no pide permisos de administrador).
2. Crea el entorno `.venv` e instala las librerías de `requirements.txt`.
3. Si no hay Tesseract, lo instala con `winget`. Puede pedir permiso de administrador; si se rechaza, el programa funciona igual, pero sin leer actas escaneadas.
4. Descarga los idiomas del OCR (`spa`, `osd`) en la carpeta `tessdata/` del proyecto.

Las siguientes ejecuciones van directo a la extracción. Si la instalación se corta, vuelve a abrir `file.bat` y retoma donde quedó. Para reinstalar las librerías desde cero, borra la carpeta `.venv`.

Si el equipo no tiene `winget` (Windows antiguo), instala **App Installer** desde la Microsoft Store, o Python desde python.org, y vuelve a ejecutar.

**Manual**, desde la carpeta del proyecto, en PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

El entorno tiene que llamarse `.venv` y estar en la raíz del proyecto: `file.bat` lo busca ahí.

Tesseract (OCR):

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
# idioma español (el instalador solo trae inglés):
Invoke-WebRequest https://github.com/tesseract-ocr/tessdata/raw/main/spa.traineddata `
  -OutFile "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tessdata\spa.traineddata"
```

El programa busca `tesseract.exe` en `C:\Program Files\Tesseract-OCR\` y en `%LOCALAPPDATA%\Programs\Tesseract-OCR\`. Si lo instalas en otra carpeta, agrégala al `PATH`. Si la ruta de instalación es distinta, copia `spa.traineddata` en la carpeta `tessdata` de esa instalación.

## Ejecución

**Opción 1 (doble clic):** abre `file.bat`. Instala lo que falte (ver arriba), ejecuta la extracción y al final muestra `[SUCCESS]` o `[ERROR]` con el código de salida. La ventana queda abierta hasta que pulses una tecla.

**Opción 2 (consola):**

```powershell
.venv\Scripts\python.exe local\extraer_local.py
```

El programa pide una ruta (puedes pegarla con comillas o sin ellas):

- **Una ubicación con varias sedes:** procesa todas las subcarpetas con nombre de sede.
- **Una sola sede:** procesa solo esa.

Las carpetas de sede deben llamarse `NNNN-SEDENNN-MUNICIPIO-NOMBRE` (por ejemplo `0155-SEDE155-…`). El ID de la sede sale de ese nombre; si ninguna carpeta lo cumple, el programa termina con un error. Los nombres que no siguen el formato exacto pero se pueden interpretar se procesan igual y quedan con un aviso en el log.

### Qué genera

Dentro de cada sede se crea una carpeta nueva `EXTRACCION_ACTAS_<DD-MM-YYYY_HH-MM-SS>`, una por cada ejecución: las anteriores no se tocan y quedan como historial. Contiene:

- Las actas renombradas como `TIPO_ID_DD-MM-YYYY.pdf` (por ejemplo `VISITA_155_01-06-2026.pdf`). Si dos coinciden en nombre se añade `_2`, `_3`…
- `EQUIPOS_<ID>.xlsx` e `INFORME_<ID>.txt` (ver [Equipos](#equipos-alcance--entrega)).

Los archivos originales no se modifican.

Al terminar se muestra un resumen por sede (actas encontradas o error). Si una sede no se puede escribir (archivo abierto, OneDrive sincronizando, permisos), las demás se escriben igual.

### Logs

Cada ejecución crea `logs/extraccion_<AAAAMMDD_HHMMSS>.log`:

- En consola solo aparece lo esencial (nivel INFO).
- En el archivo queda todo el detalle (DEBUG), con las trazas completas de los errores. Es lo primero que conviene revisar si algo falla.

### Códigos de salida

| Código | Significado |
|---|---|
| 0 | Todo correcto |
| 1 | Ruta inválida, sin sedes válidas, error en `reglas.json`, o alguna sede con error |
| 130 | Cancelado con Ctrl+C durante el proceso (no se escribe nada) |

### Problemas frecuentes

- **Falla la instalación de librerías**: revisa la conexión a internet y vuelve a abrir `file.bat`.
- **Las actas escaneadas no aparecen**: falta Tesseract o el idioma `spa`. Lo confirma el log.
- **`No encontré carpetas con formato NNNN-SEDENNN-…`**: la ruta no es una sede ni contiene sedes. Revisa los nombres de las carpetas.
- **Error al escribir una sede**: cierra el Excel o el PDF abiertos de esa sede, o espera a que OneDrive termine de sincronizar, y vuelve a ejecutar.

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

## Equipos (alcance / entrega)

Con las actas de ALCANCE y ENTREGA de cada sede se generan, junto a las actas:

- `EQUIPOS_<ID>.xlsx`: Fuente / Fecha / Nombre / Marca / Serial del acta **más reciente**, solo equipos con serial.
  `Fuente` es el tipo de acta de donde sale la información (`ALCANCE` o `ENTREGA`) y `Fecha`, su fecha.
- `INFORME_<ID>.txt`: lo que cambia frente a las actas más antiguas (coinciden, cambian de nombre, no aparecen,
  nuevos y diferencias de marca). Si solo hay un acta, lo indica.

El cruce entre actas se hace **por serial**, no por el orden de la tabla: `POE1_…` de la entrega se relaciona
con el Punto PoE del alcance que tenga su mismo serial, y el informe muestra el nombre original.

Los nombres se relacionan por palabras clave definidas en `reglas.json` (`equipos` y `marcas`):
`AP Outdoor` del alcance = `SERIAL_APOUTDOOR_CAMBIUMNETWORKS_…` de la entrega. Para un equipo nuevo, añade su clave allí.
Al comparar seriales, `O`/`0` e `I`/`1` se consideran iguales (errores típicos del OCR).

## Cambios de serial (soporte técnico / soporte de mejora)

Las actas de `SOPORTE TECNICO` y `SOPORTE DE MEJORA` se leen **de la más antigua a la más reciente**
(las que no tienen fecha, al final). De cada una se toma la sección `OBSERVACIONES` y se buscan los seriales:
según la palabra que va justo antes, el serial **sale** (`sale`, `retirado`, `daño`, `quemado`, `reemplazo del`…)
o **entra** (`entra`, `instalado`, `por el`, `nuevo`…). Cada serial que sale se empareja con el siguiente que entra.

En `EQUIPOS_<ID>.xlsx` todas las hojas empiezan con **ID** (de la carpeta: `0155-SEDE155-…` → `155`) y
**Carpeta** (nombre completo de la carpeta de la sede), y se agrega:

- Hoja **Final** (la primera): una fila por equipo, cambie o no. Acta base, serial original (el primero de
  toda su historia), serial actual en la sede, estado (`Sin cambios` / `Cambió N veces`), número de cambios,
  fecha y acta del último cambio, historial completo (`fecha: X → Y (acta) | …`) y verificación.
  Un cambio que no encaja con ningún equipo del acta base sale en su propia fila como `No está en el acta base`.
- Columna **Serial vigente** en la hoja `Equipos`: el serial tras aplicar todos los cambios del mismo equipo (X → Y → Z).
- Hoja **Cambios de serial**: Fecha / Acta / Soporte / Equipo / Serial retirado / Serial instalado / Verificación.
  `Verificación` es `OK` si el serial retirado figuraba instalado antes (en un alcance/entrega o en un cambio
  anterior); si no, `REVISAR` (suele indicar un acta que falta o que no se pudo leer).
- Hoja **Observaciones**: el texto de la sección de cada acta de soporte, para revisarlo a mano.

Las actas escaneadas necesitan Tesseract (OCR) con el idioma español; sin él quedan fuera y se avisa en el log.
Las páginas escaneadas de cabeza o de lado se enderezan solas antes de leerlas. Ver [Instalación](#instalación).

## Pruebas

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
