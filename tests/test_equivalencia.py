import numpy as np
import pytest
from app.forecast import (
    calcular_secuencial, calcular_con_hilos, calcular_paralelo, cerrar_pools,
)

def construir_tareas(n, muestras=300, horizonte=6, semilla=42):
    rng = np.random.default_rng(semilla)
    x = np.arange(muestras, dtype=np.float64)
    return [
        (f"PL-{i + 1:03d}",
         (20 + i + (0.001 + (i % 10) * 0.0001) * x + rng.normal(0, 0.5, muestras)).tolist(),
         horizonte)
        for i in range(n)
    ]

@pytest.fixture(scope="module", autouse=True)
def _cerrar_pools():
    yield
    cerrar_pools()

def _comparar(ref, cand):
    assert [r["planta_id"] for r in ref] == [c["planta_id"] for c in cand]
    for r, c in zip(ref, cand):
        assert np.allclose(r["predicciones"], c["predicciones"], rtol=1e-9, atol=1e-9)

@pytest.mark.parametrize("n", [40, 80])
@pytest.mark.parametrize("workers", [1, 2, 4])
@pytest.mark.parametrize("funcion", [calcular_con_hilos, calcular_paralelo])
def test_paralelo_equivale_a_secuencial(n, workers, funcion):
    tareas = construir_tareas(n)
    _comparar(calcular_secuencial(tareas), funcion(tareas, max_workers=workers))