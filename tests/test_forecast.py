import numpy as np
import pytest

from app.forecast import (
    calcular_con_hilos,
    calcular_distribuido,
    calcular_paralelo,
    calcular_secuencial,
)


def test_regresion_lineal_predice_tendencia():
    tareas = [("PL-001", [1.0, 2.0, 3.0], 2)]
    resultado = calcular_secuencial(tareas)
    assert np.allclose(resultado[0]["predicciones"], [4.0, 5.0])


def test_calculo_paralelo_con_varias_plantas():
    tareas = [
        ("PL-001", [1.0, 2.0, 3.0], 2),
        ("PL-002", [10.0, 12.0, 14.0], 2),
    ]
    resultado = calcular_paralelo(tareas, max_workers=2)
    assert len(resultado) == 2
    assert {item["planta_id"] for item in resultado} == {"PL-001", "PL-002"}
    assert np.allclose(resultado[0]["predicciones"], [4.0, 5.0])


def test_calculo_con_hilos_es_equivalente():
    tareas = [
        ("PL-001", [1.0, 2.0, 3.0], 2),
        ("PL-002", [10.0, 12.0, 14.0], 2),
    ]
    secuencial = calcular_secuencial(tareas)
    resultado = calcular_con_hilos(tareas, max_workers=2)
    assert len(resultado) == 2
    for esperado, obtenido in zip(secuencial, resultado):
        assert esperado["planta_id"] == obtenido["planta_id"]
        assert np.allclose(esperado["predicciones"], obtenido["predicciones"])


def test_calcular_distribuido_selecciona_backend():
    tareas = [
        ("PL-001", [1.0, 2.0, 3.0], 2),
        ("PL-002", [10.0, 12.0, 14.0], 2),
    ]
    backend, workers, resultados = calcular_distribuido(
        tareas, modo="paralelo", max_workers=2, backend="thread"
    )
    assert backend == "thread"
    assert workers == 2
    assert len(resultados) == 2

    backend, workers, _ = calcular_distribuido(tareas, modo="secuencial")
    assert backend == "secuencial"
    assert workers == 1


def test_serie_invalida():
    with pytest.raises(ValueError):
        calcular_secuencial([("PL-001", [1.0], 2)])
    with pytest.raises(ValueError):
        calcular_secuencial([("PL-001", [1.0, 2.0], 0)])
