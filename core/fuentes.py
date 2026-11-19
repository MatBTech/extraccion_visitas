"""Fuentes de documentos. Ambas exponen la misma interfaz, así el núcleo no sabe si lee disco o SharePoint.

Interfaz:
  hijos_carpetas(ref) -> [(nombre, ref_hijo)]
  hijos_archivos(ref) -> [(nombre, ref_hijo)]
  leer(ref) -> bytes          (solo lectura)
  ruta(ref) -> str             (para el inventario)
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import requests

GRAPH = "https://graph.microsoft.com/v1.0"


class FuenteLocal:
    """Carpetas del PC (o de OneDrive/SharePoint sincronizado)."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)

    def hijos_carpetas(self, ref: Path):
        return sorted(((p.name, p) for p in ref.iterdir() if p.is_dir()), key=lambda x: x[0])

    def hijos_archivos(self, ref: Path):
        return sorted(((p.name, p) for p in ref.iterdir() if p.is_file()), key=lambda x: x[0])

    def leer(self, ref: Path) -> bytes:
        return ref.read_bytes()

    def ruta(self, ref: Path) -> str:
        return str(ref.relative_to(self.raiz)).replace("\\", "/")


class FuenteGraph:
    """SharePoint vía Microsoft Graph, con token delegado de usuario (solo lectura)."""

    def __init__(self, token: str):
        self.sesion = requests.Session()
        self.sesion.headers["Authorization"] = f"Bearer {token}"

    def _get(self, url: str, intentos: int = 4, **kwargs):
        """GET con reintentos ante límites de Graph (429/503/504) y cortes de red."""
        for intento in range(intentos):
            ultimo = intento == intentos - 1
            try:
                r = self.sesion.get(url, timeout=60, **kwargs)
            except (requests.ConnectionError, requests.Timeout):
                if ultimo:
                    raise
                time.sleep(2 ** intento)
                continue
            if r.status_code in (429, 503, 504) and not ultimo:
                espera = r.headers.get("Retry-After", "")
                # Retry-After puede venir como fecha HTTP; en ese caso se usa el backoff.
                time.sleep(int(espera) if espera.isdigit() else 2 ** intento)
                continue
            if r.status_code in (401, 403):
                raise PermissionError(f"Graph {r.status_code}: token vencido o sin permiso para {url}")
            r.raise_for_status()
            return r

    def _hijos(self, ref: dict) -> list[dict]:
        url = (f"{GRAPH}/drives/{ref['drive']}/items/{ref['id']}/children"
               f"?$select=id,name,folder,file&$top=200")
        items: list[dict] = []
        while url:
            data = self._get(url).json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    @staticmethod
    def _ref_hijo(ref: dict, item: dict) -> dict:
        return {"drive": ref["drive"], "id": item["id"], "ruta": f"{ref['ruta']}/{item['name']}"}

    def hijos_carpetas(self, ref: dict):
        return [(i["name"], self._ref_hijo(ref, i)) for i in self._hijos(ref) if "folder" in i]

    def hijos_archivos(self, ref: dict):
        return [(i["name"], self._ref_hijo(ref, i)) for i in self._hijos(ref) if "file" in i]

    def leer(self, ref: dict) -> bytes:
        return self._get(f"{GRAPH}/drives/{ref['drive']}/items/{ref['id']}/content").content

    def ruta(self, ref: dict) -> str:
        return ref["ruta"]

    def raiz_desde_url(self, url: str) -> dict:
        """Resuelve un enlace de SharePoint (incluido uno de solo vista) a una carpeta."""
        codigo = "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        item = self._get(f"{GRAPH}/shares/{codigo}/driveItem?$select=id,name,folder,parentReference").json()
        if "folder" not in item:
            raise ValueError("El enlace no apunta a una carpeta.")
        return {"drive": item["parentReference"]["driveId"], "id": item["id"], "ruta": item["name"]}
