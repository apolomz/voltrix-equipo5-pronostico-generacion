"""Pronóstico NumPy con ejecución secuencial, por hilos o por procesos.

La unidad de descomposición es una planta: cada tarea recibe su propia serie
histórica y produce sus predicciones sin modificar estado compartido.
"""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import atexit
import multiprocessing
import os
from typing import Any

import numpy as np

_PROCESS_POOL: ProcessPoolExecutor | None = None
_PROCESS_WORKERS: int | None = None
_THREAD_POOL: ThreadPoolExecutor | None = None
_THREAD_WORKERS: int | None = None


def _calcular_una_planta(tarea: tuple[str, list[float], int]) -> dict[str, Any]:
    """Calcula una regresión lineal para una planta (función serializable)."""
    planta_id, historico, horizonte = tarea
    y = np.asarray(historico, dtype=np.float64)

    if y.ndim != 1 or y.size < 2:
        raise ValueError(f"La planta {planta_id} requiere al menos 2 observaciones.")
    if not np.isfinite(y).all():
        raise ValueError(f"La serie histórica de {planta_id} contiene valores no válidos.")

    x = np.arange(y.size, dtype=np.float64)
    pendiente, intercepto = np.polyfit(x, y, deg=1)
    x_futuro = np.arange(y.size, y.size + horizonte, dtype=np.float64)
    estimaciones = np.maximum(intercepto + pendiente * x_futuro, 0.0)

    return {
        "planta_id": planta_id,
        "predicciones": estimaciones.astype(float).tolist(),
    }


def calcular_secuencial(tareas: list[tuple[str, list[float], int]]) -> list[dict[str, Any]]:
    """Línea base: calcula las plantas una después de otra."""
    return [_calcular_una_planta(tarea) for tarea in tareas]


def _normalizar_workers(max_workers: int | None, numero_tareas: int) -> int:
    configurados = max_workers or int(os.getenv("MAX_WORKERS", "2"))
    nucleos = os.cpu_count() or 1
    return max(1, min(configurados, nucleos, numero_tareas))


def _obtener_process_pool(max_workers: int) -> ProcessPoolExecutor:
    global _PROCESS_POOL, _PROCESS_WORKERS
    if _PROCESS_POOL is None or _PROCESS_WORKERS != max_workers:
        if _PROCESS_POOL is not None:
            _PROCESS_POOL.shutdown(wait=True)
        _PROCESS_POOL = ProcessPoolExecutor(
            max_workers=max_workers, mp_context=multiprocessing.get_context("spawn")
        )
        _PROCESS_WORKERS = max_workers
    return _PROCESS_POOL


def _obtener_thread_pool(max_workers: int) -> ThreadPoolExecutor:
    global _THREAD_POOL, _THREAD_WORKERS
    if _THREAD_POOL is None or _THREAD_WORKERS != max_workers:
        if _THREAD_POOL is not None:
            _THREAD_POOL.shutdown(wait=True)
        _THREAD_POOL = ThreadPoolExecutor(max_workers=max_workers)
        _THREAD_WORKERS = max_workers
    return _THREAD_POOL


def calcular_paralelo(
    tareas: list[tuple[str, list[float], int]], max_workers: int | None = None
) -> list[dict[str, Any]]:
    """Descompone el lote por planta y ejecuta las tareas en procesos."""
    if not tareas:
        return []
    if len(tareas) == 1:
        return calcular_secuencial(tareas)

    workers = _normalizar_workers(max_workers, len(tareas))
    return list(_obtener_process_pool(workers).map(_calcular_una_planta, tareas))


def calcular_con_hilos(
    tareas: list[tuple[str, list[float], int]], max_workers: int | None = None
) -> list[dict[str, Any]]:
    """Variante experimental: descompone el lote por planta usando hilos."""
    if not tareas:
        return []
    if len(tareas) == 1:
        return calcular_secuencial(tareas)

    workers = _normalizar_workers(max_workers, len(tareas))
    return list(_obtener_thread_pool(workers).map(_calcular_una_planta, tareas))


def cerrar_pools() -> None:
    """Cierra los pools reutilizables al terminar el proceso de la API."""
    global _PROCESS_POOL, _PROCESS_WORKERS, _THREAD_POOL, _THREAD_WORKERS
    if _PROCESS_POOL is not None:
        _PROCESS_POOL.shutdown(wait=True)
        _PROCESS_POOL = None
        _PROCESS_WORKERS = None
    if _THREAD_POOL is not None:
        _THREAD_POOL.shutdown(wait=True)
        _THREAD_POOL = None
        _THREAD_WORKERS = None


atexit.register(cerrar_pools)


def calcular_distribuido(
    tareas: list[tuple[str, list[float], int]],
    max_workers: int | None = None,
    backend: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Selecciona el backend configurable y devuelve su nombre con el resultado."""
    seleccionado = (backend or os.getenv("PARALLEL_BACKEND", "thread")).strip().lower()
    if len(tareas) <= 1:
        return "secuencial", calcular_secuencial(tareas)
    if seleccionado == "thread":
        return "thread", calcular_con_hilos(tareas, max_workers=max_workers)
    if seleccionado == "process":
        return "process", calcular_paralelo(tareas, max_workers=max_workers)
    raise ValueError("PARALLEL_BACKEND debe ser 'thread' o 'process'.")
