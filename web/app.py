"""Versión web: el usuario inicia sesión con Microsoft y pega un enlace de SharePoint
(de solo vista). La app lee las carpetas y devuelve un ZIP. No escribe nada en SharePoint.

Variables de entorno necesarias:
  FLASK_SECRET_KEY, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
  GRAPH_TENANT_ID (opcional, por defecto 'common'),
  GRAPH_REDIRECT_URI (opcional, por defecto http://localhost:5000/callback)
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import uuid
from pathlib import Path

import msal
from flask import Flask, abort, redirect, render_template_string, request, send_file, session, url_for

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.fuentes import FuenteGraph  # noqa: E402
from core.proceso import cargar_reglas, procesar, zip_global  # noqa: E402
from core.texto import parsear_sede  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

CLIENT_ID = os.environ["GRAPH_CLIENT_ID"]
CLIENT_SECRET = os.environ["GRAPH_CLIENT_SECRET"]
TENANT = os.environ.get("GRAPH_TENANT_ID", "common")
REDIRECT_URI = os.environ.get("GRAPH_REDIRECT_URI", "http://localhost:5000/callback")
SCOPES = ["Files.Read.All"]  # solo lectura

# Prototipo: los tokens viven en memoria del servidor. En producción usar un almacén persistente.
TOKENS: dict[str, str] = {}
REGLAS = cargar_reglas(RAIZ / "reglas.json")

PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Extracción de actas</title></head>
<body style="font-family:sans-serif;max-width:820px;margin:2rem auto;line-height:1.4">
<h1>Extracción de actas</h1>
{% if error %}<p style="color:#b00">{{ error }}</p>{% endif %}
{% if not sesion %}
  <p>Inicia sesión con tu cuenta de Microsoft para leer las carpetas de SharePoint.</p>
  <p><a href="/login">Iniciar sesión</a></p>
{% else %}
  <form method="post" action="/buscar">
    <label>Enlace de SharePoint (ubicación con varias sedes, o una sede):<br>
      <input name="url" size="110" required>
    </label>
    <button type="submit">Buscar sedes</button>
  </form>
  {% if sedes %}
  <form method="post" action="/procesar" style="margin-top:1.5rem">
    <p>Selecciona las sedes a procesar:</p>
    {% for info, valor in sedes %}
      <label><input type="checkbox" name="sede" value="{{ valor }}" checked>
        ID {{ info.id }} · {{ info.municipio }} · {{ info.nombre }}</label><br>
    {% endfor %}
    <button type="submit">Generar ZIP</button>
  </form>
  {% endif %}
{% endif %}
</body></html>
"""


def _msal() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT}",
        client_credential=CLIENT_SECRET,
    )


def _fuente() -> FuenteGraph | None:
    token = TOKENS.get(session.get("uid", ""))
    return FuenteGraph(token) if token else None


def _codificar(info: dict, ref: dict) -> str:
    datos = json.dumps({"info": info, "ref": ref}).encode()
    return base64.urlsafe_b64encode(datos).decode()


def _decodificar(valor: str) -> tuple[dict, dict]:
    datos = json.loads(base64.urlsafe_b64decode(valor.encode()).decode())
    return datos["info"], datos["ref"]


@app.route("/")
def inicio():
    return render_template_string(PLANTILLA, sesion=_fuente() is not None, sedes=None, error=None)


@app.route("/login")
def login():
    estado = uuid.uuid4().hex
    session["estado"] = estado
    url = _msal().get_authorization_request_url(SCOPES, state=estado, redirect_uri=REDIRECT_URI)
    return redirect(url)


@app.route("/callback")
def callback():
    if request.args.get("state") != session.get("estado"):
        abort(400)
    if "error" in request.args:
        return f"No se completó el inicio de sesión: {request.args.get('error_description', '')}", 400
    res = _msal().acquire_token_by_authorization_code(
        request.args["code"], scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    if "access_token" not in res:
        return f"No se obtuvo el token: {res.get('error_description', '')}", 400
    uid = uuid.uuid4().hex
    TOKENS[uid] = res["access_token"]
    session["uid"] = uid
    return redirect(url_for("inicio"))


@app.route("/buscar", methods=["POST"])
def buscar():
    fuente = _fuente()
    if fuente is None:
        return redirect(url_for("login"))
    try:
        raiz = fuente.raiz_desde_url(request.form.get("url", "").strip())
        info_raiz = parsear_sede(raiz["ruta"])
        if info_raiz:
            encontradas = [(info_raiz, raiz)]
        else:
            encontradas = [(parsear_sede(n), r) for n, r in fuente.hijos_carpetas(raiz) if parsear_sede(n)]
    except Exception as e:  # noqa: BLE001
        return render_template_string(PLANTILLA, sesion=True, sedes=None,
                                      error=f"No se pudo leer el enlace: {e}")
    if not encontradas:
        return render_template_string(PLANTILLA, sesion=True, sedes=None,
                                      error="No encontré carpetas de sede en ese enlace.")
    vistas = [(info, _codificar(info, ref)) for info, ref in encontradas]
    return render_template_string(PLANTILLA, sesion=True, sedes=vistas, error=None)


@app.route("/procesar", methods=["POST"])
def procesar_web():
    fuente = _fuente()
    if fuente is None:
        return redirect(url_for("login"))
    seleccion = request.form.getlist("sede")
    if not seleccion:
        return render_template_string(PLANTILLA, sesion=True, sedes=None,
                                      error="Selecciona al menos una sede.")
    sedes = [_decodificar(v) for v in seleccion]
    resultados = procesar(fuente, sedes, REGLAS)
    return send_file(io.BytesIO(zip_global(resultados)), mimetype="application/zip",
                     as_attachment=True, download_name="actas_sedes.zip")


if __name__ == "__main__":
    app.run(port=5000, debug=False)
