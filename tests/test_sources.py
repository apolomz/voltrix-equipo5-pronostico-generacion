from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from app.config import Config
from app.sources.errors import (
    ConfiguracionIncompletaError,
    DependenciaError,
    PlantaNoEncontradaError,
)
from app.sources.http import ClienteHttp
from app.sources.service import DataInputService
from app.sources.telemetria import TelemetriaClient

DESDE = datetime(2026, 11, 1, tzinfo=timezone.utc)
HASTA = datetime(2026, 11, 2, tzinfo=timezone.utc)


def _config(**cambios):
    base = Config.desde_entorno()
    valores = dict(
        demo_mode=False,
        inventario_url="http://mock/eq1",
        telemetria_url="http://mock/eq2",
        reportes_url="http://mock/eq4",
        validar_activos=True,
        reportes_generar_si_vacio=False,
        demo_fallback=False,
    )
    valores.update(cambios)
    return replace(base, **valores)


def _handler(reportes_vacio: bool = False, telemetria: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        ruta = request.url.path
        if ruta == "/eq1/plantas":
            return httpx.Response(
                200,
                json={
                    "datos": [{"id": "PL-001", "nombre": "Planta 1", "estado": "operativo"}],
                    "total": 1,
                    "limit": 200,
                    "offset": 0,
                },
                headers={"X-Request-Id": "mock-1"},
            )
        if ruta == "/eq1/plantas/PL-999":
            return httpx.Response(404, json={"codigo": "NO_ENCONTRADO"})
        if ruta == "/eq1/activos":
            return httpx.Response(
                200,
                json={
                    "datos": [
                        {
                            "id": "PL-001-PS-01",
                            "plantaId": "PL-001",
                            "tipo": "panel_solar",
                            "estado": "operativo",
                            "capacidadNominalKw": 120,
                        }
                    ],
                    "total": 1,
                },
            )
        if ruta == "/eq4/reportes/generacion":
            if reportes_vacio:
                return httpx.Response(200, json={"datos": [], "total": 0})
            datos = [
                {
                    "plantaId": "PL-001",
                    "periodoInicio": f"2026-11-01T{hora:02d}:00:00Z",
                    "energiaKwh": 10.0 + hora,
                    "granularidad": "hora",
                }
                for hora in range(24)
            ]
            return httpx.Response(200, json={"datos": datos, "total": 24})
        if ruta == "/eq2/telemetria/PL-001":
            if not telemetria:
                return httpx.Response(200, json=[])
            datos = [
                {
                    "plantaId": "PL-001",
                    "activoId": "PL-001-PS-01",
                    "fechaHora": f"2026-11-01T{hora:02d}:00:00Z",
                    "metrica": "potencia",
                    "valor": 10.0,
                    "unidad": "kW",
                }
                for hora in range(24)
            ]
            return httpx.Response(200, json=datos)
        return httpx.Response(404, json={"codigo": "NO_ENCONTRADO", "ruta": ruta})

    return handler


def test_data_service_usa_reportes():
    cliente = httpx.Client(transport=httpx.MockTransport(_handler()))
    servicio = DataInputService(_config(), http_client=cliente)
    try:
        resultado = servicio.obtener_series(["PL-001"], "hora", DESDE, HASTA)
    finally:
        servicio.cerrar()

    assert resultado.origen_datos == "dependencias"
    assert len(resultado.series) == 1
    assert len(resultado.series[0].puntos) == 24
    assert resultado.series[0].puntos[0].generacion_kwh == 10.0


def test_data_service_cae_a_telemetria():
    cliente = httpx.Client(transport=httpx.MockTransport(_handler(reportes_vacio=True, telemetria=True)))
    servicio = DataInputService(_config(), http_client=cliente)
    try:
        resultado = servicio.obtener_series(["PL-001"], "hora", DESDE, HASTA)
    finally:
        servicio.cerrar()

    assert resultado.origen_datos == "dependencias"
    assert len(resultado.series[0].puntos) == 24
    assert all(punto.generacion_kwh == 10.0 for punto in resultado.series[0].puntos)
    assert any("Telemetría" in aviso for aviso in resultado.advertencias)


def test_data_service_planta_desconocida():
    cliente = httpx.Client(transport=httpx.MockTransport(_handler()))
    servicio = DataInputService(_config(validar_activos=False), http_client=cliente)
    try:
        with pytest.raises(PlantaNoEncontradaError):
            servicio.obtener_series(["PL-999"], "hora", DESDE, HASTA)
    finally:
        servicio.cerrar()


def test_data_service_configuracion_incompleta():
    servicio = DataInputService(_config(inventario_url=None, validar_activos=False))
    try:
        with pytest.raises(ConfiguracionIncompletaError):
            servicio.obtener_series(["PL-001"], "hora", DESDE, HASTA)
    finally:
        servicio.cerrar()


def test_cliente_http_reintenta_503_y_propaga_headers():
    llamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        if len(llamadas) == 1:
            return httpx.Response(503, json={"mensaje": "arrancando"})
        return httpx.Response(200, json={"ok": True})

    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    api = ClienteHttp(
        "http://mock", "equipo-2", "Telemetría", retries=1, client=cliente
    )
    assert api.get_json("/x", request_id="req-123") == {"ok": True}
    assert len(llamadas) == 2
    assert llamadas[1].headers["X-Equipo-Consumidor"] == "equipo-5"
    assert llamadas[1].headers["X-Request-Id"] == "req-123"


def test_telemetria_sigue_x_next_offset():
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        if offset == 0:
            return httpx.Response(
                200,
                json=[
                    {
                        "plantaId": "PL-001",
                        "fechaHora": "2026-11-01T00:00:00Z",
                        "metrica": "potencia",
                        "valor": 1,
                        "unidad": "kW",
                    },
                    {
                        "plantaId": "PL-001",
                        "fechaHora": "2026-11-01T01:00:00Z",
                        "metrica": "potencia",
                        "valor": 2,
                        "unidad": "kW",
                    },
                ],
                headers={"X-Next-Offset": "2"},
            )
        return httpx.Response(
            200,
            json=[
                {
                    "plantaId": "PL-001",
                    "fechaHora": "2026-11-01T02:00:00Z",
                    "metrica": "potencia",
                    "valor": 3,
                    "unidad": "kW",
                }
            ],
        )

    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    api = TelemetriaClient(
        ClienteHttp("http://mock", "equipo-2", "Telemetría", client=cliente)
    )
    lecturas = api.lecturas("PL-001", DESDE, HASTA)
    assert len(lecturas) == 3


def test_inventario_caido_devuelve_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"mensaje": "sin servicio"})

    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    servicio = DataInputService(_config(validar_activos=False), http_client=cliente)
    try:
        with pytest.raises(DependenciaError) as exc:
            servicio.obtener_series(["PL-001"], "hora", DESDE, HASTA)
    finally:
        servicio.cerrar()
    assert exc.value.status_code == 502
