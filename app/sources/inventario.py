"""Adaptador para Inventario de Activos (Equipo 1)."""

from __future__ import annotations

from urllib.parse import quote

from .http import ClienteHttp
from .models import Activo, Planta, extraer_lista, extraer_total


class InventarioClient:
    def __init__(self, http: ClienteHttp) -> None:
        self.http = http

    def listar_plantas(self, request_id: str | None = None) -> list[Planta]:
        plantas: list[Planta] = []
        offset = 0
        limite = 200
        while True:
            payload = self.http.get_json(
                "/plantas",
                params={"limit": limite, "offset": offset},
                request_id=request_id,
            )
            items = extraer_lista(payload, ("datos", "plantas", "data", "items"))
            plantas.extend(_plantas(items))
            total = extraer_total(payload)
            offset += len(items)
            if not isinstance(payload, dict) or not items or len(items) < limite:
                break
            if total is not None and offset >= total:
                break
        return _deduplicar_plantas(plantas)

    def obtener_planta(self, planta_id: str, request_id: str | None = None) -> Planta | None:
        try:
            payload = self.http.get_json(
                f"/plantas/{quote(planta_id, safe='')}", request_id=request_id
            )
        except Exception as exc:
            if getattr(exc, "status_code_upstream", None) == 404:
                return None
            raise
        if isinstance(payload, dict) and "datos" in payload and isinstance(payload["datos"], dict):
            payload = payload["datos"]
        try:
            return Planta.model_validate(payload)
        except Exception:
            return None

    def listar_activos(self, planta_id: str, request_id: str | None = None) -> list[Activo]:
        activos: list[Activo] = []
        offset = 0
        limite = 200
        while True:
            payload = self.http.get_json(
                "/activos",
                params={"plantaId": planta_id, "limit": limite, "offset": offset},
                request_id=request_id,
            )
            items = extraer_lista(payload, ("datos", "activos", "data", "items"))
            activos.extend(_activos(items))
            total = extraer_total(payload)
            offset += len(items)
            if not isinstance(payload, dict) or not items or len(items) < limite:
                break
            if total is not None and offset >= total:
                break
        return activos


def _plantas(items: list) -> list[Planta]:
    resultado = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            resultado.append(Planta.model_validate(item))
        except Exception:
            continue
    return resultado


def _activos(items: list) -> list[Activo]:
    resultado = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            resultado.append(Activo.model_validate(item))
        except Exception:
            continue
    return resultado


def _deduplicar_plantas(plantas: list[Planta]) -> list[Planta]:
    vistos: dict[str, Planta] = {}
    for planta in plantas:
        vistos[planta.id] = planta
    return list(vistos.values())
