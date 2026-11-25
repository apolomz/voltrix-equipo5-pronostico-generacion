"""Cliente HTTP común para las APIs de los equipos 1, 2 y 4."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .errors import DependenciaError

logger = logging.getLogger("voltrix.equipo5.upstream")

_MAX_RETRY_AFTER = 5.0



class ClienteHttp:
    """Cliente con trazabilidad, timeouts y reintentos acotados.

    Comparte un ``httpx.Client`` entre peticiones para reutilizar conexiones.
    Si no se entrega uno, crea y cierra el suyo.
    """

    def __init__(
        self,
        base_url: str,
        equipo: str,
        servicio: str,
        *,
        timeout: float = 5.0,
        retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.equipo = equipo
        self.servicio = servicio
        self.timeout = timeout
        self.retries = max(0, retries)
        self._client = client
        self._propio = client is None

    def _cliente(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    def get_json(
        self,
        ruta: str,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        *,
        con_headers: bool = False,
    ) -> Any:
        return self._request("GET", ruta, params=params, request_id=request_id, con_headers=con_headers)

    def post_json(
        self,
        ruta: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        return self._request("POST", ruta, json=json, params=params, request_id=request_id)

    def get_health(self, request_id: str | None = None) -> Any:
        return self.get_json("/health", request_id=request_id)

    def _request(
        self,
        metodo: str,
        ruta: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        request_id: str | None = None,
        con_headers: bool = False,
    ) -> Any:
        url = f"{self.base_url}{ruta}"
        headers = {
            "Accept": "application/json",
            "X-Equipo-Consumidor": "equipo-5",
        }
        if request_id:
            headers["X-Request-Id"] = request_id

        ultimo_error: Exception | None = None
        for intento in range(self.retries + 1):
            inicio = time.perf_counter()
            try:
                respuesta = self._cliente().request(
                    metodo,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=self.timeout,
                )
            except httpx.RequestError as exc:
                ultimo_error = exc
                duracion = (time.perf_counter() - inicio) * 1000
                logger.warning(
                    "upstream=%s operacion=%s status=error duracion_ms=%.1f intento=%s request_id=%s detalle=%s",
                    self.equipo,
                    ruta,
                    duracion,
                    intento + 1,
                    request_id,
                    type(exc).__name__,
                )
                if intento < self.retries:
                    time.sleep(min(0.5 * (2**intento), 3.0))
                    continue
                raise DependenciaError(
                    self.equipo,
                    self.servicio,
                    f"{metodo} {ruta}",
                    f"{self.servicio} no respondió",
                    detalle=str(exc),
                ) from exc

            duracion = (time.perf_counter() - inicio) * 1000
            logger.info(
                "upstream=%s operacion=%s status=%s duracion_ms=%.1f intento=%s request_id=%s",
                self.equipo,
                ruta,
                respuesta.status_code,
                duracion,
                intento + 1,
                request_id,
            )

            if respuesta.status_code == 429 and intento < self.retries:
                espera = _retry_after(respuesta.headers.get("Retry-After"))
                time.sleep(min(espera, _MAX_RETRY_AFTER))
                continue

            if 500 <= respuesta.status_code < 600 and intento < self.retries:
                time.sleep(min(0.5 * (2**intento), 3.0))
                continue

            if respuesta.status_code >= 400:
                detalle = _texto_error(respuesta)
                raise DependenciaError(
                    self.equipo,
                    self.servicio,
                    f"{metodo} {ruta}",
                    f"{self.servicio} respondió {respuesta.status_code}",
                    status_code=respuesta.status_code,
                    detalle=detalle,
                )

            if not respuesta.content:
                return (None, respuesta.headers) if con_headers else None

            try:
                payload = respuesta.json()
            except ValueError as exc:
                raise DependenciaError(
                    self.equipo,
                    self.servicio,
                    f"{metodo} {ruta}",
                    f"{self.servicio} devolvió una respuesta que no es JSON",
                    status_code=respuesta.status_code,
                ) from exc

            return (payload, respuesta.headers) if con_headers else payload

        raise DependenciaError(
            self.equipo,
            self.servicio,
            f"{metodo} {ruta}",
            f"{self.servicio} no respondió tras {self.retries + 1} intentos",
            detalle=str(ultimo_error) if ultimo_error else None,
        )

    def cerrar(self) -> None:
        if self._propio and self._client is not None:
            self._client.close()
            self._client = None


def _retry_after(valor: str | None) -> float:
    if not valor:
        return 0.5
    try:
        return max(0.1, float(valor))
    except ValueError:
        return 0.5


def _texto_error(respuesta: httpx.Response) -> str:
    try:
        payload = respuesta.json()
    except ValueError:
        return respuesta.text[:300]
    if isinstance(payload, dict):
        for clave in ("mensaje", "detail", "message", "error"):
            valor = payload.get(clave)
            if isinstance(valor, str):
                return valor[:300]
    return str(payload)[:300]
