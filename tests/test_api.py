from __future__ import annotations

from fastapi.testclient import TestClient

from app import store
from app.main import app


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
