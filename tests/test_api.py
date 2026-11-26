from __future__ import annotations

from fastapi.testclient import TestClient

from app import store
from app.main import app

import httpx
import threading
import pytest
from app import main

def test_health():
    with TestClient(app) as cliente:
        respuesta = cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "disponible"
    assert respuesta.json()["baseDatos"] == "ok"


def test_generar_y_consultar():
    store.limpiar()
    with TestClient(app) as cliente:
        generado = cliente.post(
            "/pronosticos/generar",
            json={
                "planta_ids": ["PL-001", "PL-002"],
                "horizonte_periodos": 3,
                "frecuencia": "hora",
            },
        )
        assert generado.status_code == 200
        datos = generado.json()
        assert datos["modo_ejecucion"] == "paralelo"
        assert datos["backend_paralelismo"] in {"thread", "process"}
        assert datos["origen_datos"] == "demo"
        assert datos["cantidad_plantas"] == 2
        assert len(datos["pronosticos"][0]["valores"]) == 3
        assert generado.headers["X-Modo-Datos"] == "demo"

        consultado = cliente.get("/pronosticos/PL-001")
    assert consultado.status_code == 200
    assert len(consultado.json()["valores"]) == 3


def test_acepta_alias_camel_case():
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/pronosticos/generar",
            json={
                "plantaIds": ["PL-001"],
                "horizontePeriodos": 2,
                "frecuencia": "dia",
            },
        )
    assert respuesta.status_code == 200
    assert respuesta.json()["cantidad_plantas"] == 1


def test_planta_desconocida():
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/pronosticos/generar",
            json={"planta_ids": ["PL-999"], "horizonte_periodos": 2},
        )
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "PLANTA_NO_ENCONTRADA"


def test_fecha_sin_zona_horaria():
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/pronosticos/generar",
            json={
                "planta_ids": ["PL-001"],
                "horizonte_periodos": 2,
                "desde": "2026-11-01T00:00:00",
            },
        )
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "SOLICITUD_INVALIDA"


def test_backend_process():
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/pronosticos/generar?modo=paralelo&backend=process&workers=2",
            json={
                "planta_ids": ["PL-001", "PL-002"],
                "horizonte_periodos": 2,
            },
        )
    assert respuesta.status_code == 200
    assert respuesta.json()["backend_paralelismo"] == "process"


def test_modo_secuencial():
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/pronosticos/generar?modo=secuencial",
            json={"planta_ids": ["PL-001", "PL-002"], "horizonte_periodos": 2},
        )
    assert respuesta.status_code == 200
    assert respuesta.json()["backend_paralelismo"] == "secuencial"
    assert respuesta.json()["metricas"]["workers"] == 1


def test_dependencias_en_demo():
    with TestClient(app) as cliente:
        respuesta = cliente.get("/dependencias/estado")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["modoDatos"] == "demo"
    assert len(datos["fuentes"]) == 3
    assert all(fuente["estado"] == "no_aplica" for fuente in datos["fuentes"])


def test_openapi_yaml_servido():
    with TestClient(app) as cliente:
        respuesta = cliente.get("/openapi.yaml")
    assert respuesta.status_code == 200
    assert "application/yaml" in respuesta.headers["content-type"]
    assert "openapi:" in respuesta.text


def test_raiz():
    with TestClient(app) as cliente:
        respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert respuesta.json()["servicio"] == "pronostico-generacion"

CUERPO = {"planta_ids": ["PL-001"], "horizonte_periodos": 2}


def _error_comun(respuesta, codigo):
    datos = respuesta.json()
    assert datos["codigo"] == codigo
    assert datos["mensaje"]
    assert datos["requestId"] == respuesta.headers["X-Request-Id"]


@pytest.mark.parametrize("cuerpo", [
    {"planta_ids": [], "horizonte_periodos": 2},
    {"planta_ids": ["PL-001"], "horizonte_periodos": 0},
    {"planta_ids": ["PL-001"], "horizonte_periodos": 169},
    {"planta_ids": ["PL-001"], "frecuencia": "semana"},
    {"planta_ids": ["PL-001"], "campo_extra": 1},
    {"planta_ids": ["PL-001"], "desde": "2026-11-05T00:00:00Z", "hasta": "2026-11-01T00:00:00Z"},
])
def test_400_cuerpo_invalido(cuerpo):
    with TestClient(app) as cliente:
        respuesta = cliente.post("/pronosticos/generar", json=cuerpo)
    assert respuesta.status_code == 400
    _error_comun(respuesta, "SOLICITUD_INVALIDA")


@pytest.mark.parametrize("query", ["modo=otro", "backend=otro", "workers=0", "workers=65"])
def test_400_query_invalida(query):
    with TestClient(app) as cliente:
        respuesta = cliente.post(f"/pronosticos/generar?{query}", json=CUERPO)
    assert respuesta.status_code == 400
    _error_comun(respuesta, "SOLICITUD_INVALIDA")


def test_get_sin_pronostico_da_404():
    store.limpiar()
    with TestClient(app) as cliente:
        respuesta = cliente.get("/pronosticos/PL-001")
    assert respuesta.status_code == 404
    _error_comun(respuesta, "NO_ENCONTRADO")


def test_cabeceras_de_paralelismo():
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/pronosticos/generar?modo=paralelo&backend=thread&workers=2", json=CUERPO | {"planta_ids": ["PL-001", "PL-002"]}
        )
    assert respuesta.status_code == 200
    assert respuesta.headers["X-Backend-Paralelismo"] == "thread"
    assert respuesta.headers["X-Workers"] == str(respuesta.json()["metricas"]["workers"])


def test_429_por_sobrecarga(monkeypatch):
    ocupado = threading.Semaphore(1)
    ocupado.acquire()
    monkeypatch.setattr(main, "_SEMAFORO_GENERACION", ocupado)
    with TestClient(app) as cliente:
        respuesta = cliente.post("/pronosticos/generar", json=CUERPO)
    assert respuesta.status_code == 429
    assert respuesta.headers["Retry-After"] == "1"
    _error_comun(respuesta, "SOBRECARGA")


def test_health_503_sin_base_de_datos(monkeypatch):
    monkeypatch.setattr(main.store, "esta_disponible", lambda: False)
    with TestClient(app) as cliente:
        respuesta = cliente.get("/health")
    assert respuesta.status_code == 503
    assert respuesta.json()["estado"] == "no_disponible"

def test_una_planta_en_paralelo_se_ejecuta_secuencial():
    with TestClient(app) as cliente:
        r = cliente.post(
            "/pronosticos/generar?modo=paralelo&backend=process&workers=4", json=CUERPO
        )
    assert r.status_code == 200
    datos = r.json()
    assert datos["modo_ejecucion"] == "secuencial"
    assert datos["backend_paralelismo"] == "secuencial"
    assert datos["metricas"]["workers"] == 1


def test_503_configuracion_incompleta(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")  # conftest ya borra las URLs
    with TestClient(app) as cliente:
        r = cliente.post("/pronosticos/generar", json=CUERPO)
    assert r.status_code == 503
    assert r.json()["codigo"] == "CONFIGURACION_INCOMPLETA"


def test_502_dependencia_caida(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("INVENTARIO_URL", "http://mock/eq1")
    monkeypatch.setenv("TELEMETRIA_URL", "http://mock/eq2")
    monkeypatch.setenv("REPORTES_URL", "http://mock/eq4")
    caido = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(503, json={"mensaje": "sin servicio"}))
    )
    with TestClient(app) as cliente:
        cliente.app.state.http_client = caido  # reemplaza el cliente creado en lifespan
        r = cliente.post("/pronosticos/generar", json=CUERPO)
    assert r.status_code == 502
    assert r.json()["codigo"] == "DEPENDENCIA_FALLIDA"


def test_400_rango_demasiado_corto():
    cuerpo = CUERPO | {
        "desde": "2026-11-01T00:00:00Z",
        "hasta": "2026-11-01T01:00:00Z",
    }
    with TestClient(app) as cliente:
        r = cliente.post("/pronosticos/generar", json=cuerpo)
    assert r.status_code == 400
    assert r.json()["codigo"] == "RANGO_INVALIDO"


def test_400_serie_invalida_del_motor(monkeypatch):
    def falla(*args, **kwargs):
        raise ValueError("La planta PL-001 requiere al menos 2 observaciones.")

    monkeypatch.setattr("app.services.pronostico.calcular_distribuido", falla)
    with TestClient(app) as cliente:
        r = cliente.post("/pronosticos/generar", json=CUERPO)
    assert r.status_code == 400
    assert r.json()["codigo"] == "SERIE_INVALIDA"


def test_400_rango_mayor_a_31_dias():
    cuerpo = CUERPO | {
        "desde": "2026-09-01T00:00:00Z",
        "hasta": "2026-11-01T00:00:00Z",
    }
    with TestClient(app) as cliente:
        r = cliente.post("/pronosticos/generar", json=cuerpo)
    assert r.status_code == 400
    assert r.json()["codigo"] == "RANGO_INVALIDO"