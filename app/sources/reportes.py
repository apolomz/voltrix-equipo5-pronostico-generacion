"""Adaptador para Reportes de Generación (Equipo 4)."""

from __future__ import annotations

from datetime import datetime

from .http import ClienteHttp
from .models import Agregado, extraer_lista, extraer_total


class ReportesClient:
    def __init__(self, http: ClienteHttp) -> None:
        self.http = http

    def historial(
        self,
        planta_id: str,
        desde: datetime,
        hasta: datetime,
        granularidad: str,
        request_id: str | None = None,
    ) -> list[Agregado]:
        agregados: list[Agregado] = []
        offset = 0
        limite = 200
        while True:
            payload = self.http.get_json(
                "/reportes/generacion",
                params={
                    "plantaId": planta_id,
                    "desde": desde.isoformat(),
                    "hasta": hasta.isoformat(),
                    "granularidad": granularidad,
                    "limit": limite,
                    "offset": offset,
                },
                request_id=request_id,
            )
            items = extraer_lista(payload, ("datos", "agregados", "data", "items"))
            agregados.extend(_agregados(items))
            total = extraer_total(payload)
            offset += len(items)
            if not isinstance(payload, dict) or not items or len(items) < limite:
                break
            if total is not None and offset >= total:
                break
        return agregados

    def generar(
        self,
        planta_ids: list[str],
        desde: datetime,
        hasta: datetime,
        granularidad: str,
        request_id: str | None = None,
    ) -> dict:
        payload = self.http.post_json(
            "/reportes/generar",
            params={"modo": "paralelo"},
            json={
                "plantaIds": planta_ids,
                "desde": desde.isoformat(),
                "hasta": hasta.isoformat(),
                "granularidad": granularidad,
                "nivel": "planta",
            },
            request_id=request_id,
        )
        return payload if isinstance(payload, dict) else {}


def _agregados(items: list) -> list[Agregado]:
    resultado = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            resultado.append(Agregado.model_validate(item))
        except Exception:
            continue
    return resultado
