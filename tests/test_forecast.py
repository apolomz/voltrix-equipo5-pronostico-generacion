import numpy as np
from fastapi.testclient import TestClient

from app.forecast import calcular_con_hilos, calcular_paralelo, calcular_secuencial
from app.main import app
from app import store


def test_regresion_lineal_predice_tendencia():
    tareas = [("P1", [1.0, 2.0, 3.0], 2)]
    resultado = calcular_secuencial(tareas)
    assert np.allclose(resultado[0]["predicciones"], [4.0, 5.0])


def test_calculo_paralelo_con_varias_plantas():
    tareas = [
        ("P1", [1.0, 2.0, 3.0], 2),
        ("P2", [10.0, 12.0, 14.0], 2),
    ]
    resultado = calcular_paralelo(tareas, max_workers=2)
    assert len(resultado) == 2
    assert {item["planta_id"] for item in resultado} == {"P1", "P2"}
    assert np.allclose(resultado[0]["predicciones"], [4.0, 5.0])


def test_endpoints_basicos():
    store.limpiar()
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    generated = client.post(
        "/pronosticos/generar",
        json={
            "planta_ids": ["PLANTA-001", "PLANTA-002"],
            "horizonte_periodos": 3,
            "frecuencia": "hora",
        },
    )
    assert generated.status_code == 200
    assert generated.json()["modo_ejecucion"] == "paralelo"
    assert generated.json()["backend_paralelismo"] == "thread"
    assert generated.json()["cantidad_plantas"] == 2

    consulted = client.get("/pronosticos/PLANTA-001")
    assert consulted.status_code == 200
    assert len(consulted.json()["valores"]) == 3


def test_calculo_paralelo_con_hilos():
    tareas = [
        ("P1", [1.0, 2.0, 3.0], 2),
        ("P2", [10.0, 12.0, 14.0], 2),
    ]
    secuencial = calcular_secuencial(tareas)
    resultado = calcular_con_hilos(tareas, max_workers=2)
    assert len(resultado) == 2
    for esperado, obtenido in zip(secuencial, resultado):
        assert esperado["planta_id"] == obtenido["planta_id"]
        assert np.allclose(esperado["predicciones"], obtenido["predicciones"])
