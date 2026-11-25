"""Adaptador para Telemetría de Plantas (Equipo 2)."""

from __future__ import annotations

from datetime import datetime

from .http import ClienteHttp
from .models import Lectura, extraer_lista


class TelemetriaClient:
    def __init__(self, http: ClienteHttp, max_paginas: int = 50) -> None:
        self.http = http
        self.max_paginas = max_paginas

    def lecturas(
        self,
        planta_id: str,
        desde: datetime,
        hasta: datetime,
        request_id: str | None = None,
    ) -> list[Lectura]:
        lecturas: list[Lectura] = []
        offset = 0
        limite = 200
        for _ in range(self.max_paginas):
            payload, headers = self.http.get_json(
                f"/telemetria/{planta_id}",
                params={
                    "desde": desde.isoformat(),
                    "hasta": hasta.isoformat(),
                    "limit": limite,
                    "offset": offset,
                },
                request_id=request_id,
                con_headers=True,
            )
            items = extraer_lista(payload, ("datos", "lecturas", "data", "items"))
            lecturas.extend(_lecturas(items))
            siguiente = headers.get("X-Next-Offset") if headers is not None else None
            if siguiente:
                try:
                    offset = int(siguiente)
                except ValueError:
                    break
            elif len(items) >= limite:
                offset += len(items)
            else:
                break
        return lecturas


def _lecturas(items: list) -> list[Lectura]:
    resultado = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            resultado.append(Lectura.model_validate(item))
        except Exception:
            continue
    return resultado
