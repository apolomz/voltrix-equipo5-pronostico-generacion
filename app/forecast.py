"""Motor de pronóstico con descomposición de datos planta por planta.

La unidad de trabajo es una planta: recibe su propia serie histórica y produce
sus predicciones sin compartir estado mutable con las demás. Se ofrecen tres
caminos equivalentes:

* secuencial: línea base, una planta después de otra;
* hilos: ``ThreadPoolExecutor`` (NumPy libera el GIL en parte del cálculo);
* procesos: ``ProcessPoolExecutor`` con ``chunksize`` para reducir el coste
  de serializar muchas tareas pequeñas.

``ejecutar`` centraliza la selección para que la API y el benchmark midan
exactamente la misma función.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import atexit
import multiprocessing
import os
import threading
from typing import Any

import numpy as np

_LOCK_POOLS = threading.Lock()
_PROCESS_POOL: ProcessPoolExecutor | None = None
_PROCESS_WORKERS: int | None = None
_THREAD_POOL: ThreadPoolExecutor | None = None
_THREAD_WORKERS: int | None = None


def _calcular_una_planta(tarea: tuple[str, list[float], int]) -> dict[str, Any]:
    """Calcula una regresión lineal para una planta (función serializable)."""

    planta_id, historico, horizonte = tarea
    if horizonte < 1:
        raise ValueError(f"La planta {planta_id} requiere un horizonte mayor o igual a 1.")

    y = np.asarray(historico, dtype=np.float64)
    if y.ndim != 1 or y.size < 2:
        raise ValueError(f"La planta {planta_id} requiere al menos 2 observaciones.")
    if not np.isfinite(y).all():
        raise ValueError(f"La serie histórica de {planta_id} contiene valores no válidos.")

    x = np.arange(y.size, dtype=np.float64)
    try:
        pendiente, intercepto = np.polyfit(x, y, deg=1)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"No se pudo ajustar la regresión de {planta_id}.") from exc

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
    return max(1, min(configurados, nucleos, max(1, numero_tareas)))


def _obtener_process_pool(max_workers: int) -> ProcessPoolExecutor:
    global _PROCESS_POOL, _PROCESS_WORKERS
    with _LOCK_POOLS:
        if _PROCESS_POOL is None or _PROCESS_WORKERS != max_workers:
            if _PROCESS_POOL is not None:
                _PROCESS_POOL.shutdown(wait=True)
            _PROCESS_POOL = ProcessPoolExecutor(
                max_workers=max_workers,
                mp_context=multiprocessing.get_context("spawn"),
            )
            _PROCESS_WORKERS = max_workers
        return _PROCESS_POOL


def _obtener_thread_pool(max_workers: int) -> ThreadPoolExecutor:
    global _THREAD_POOL, _THREAD_WORKERS
    with _LOCK_POOLS:
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
    # Un chunk por cada 4 tareas y worker reduce el IPC sin desbalancear el lote.
    chunksize = max(1, len(tareas) // (workers * 4))
    pool = _obtener_process_pool(workers)
    return list(pool.map(_calcular_una_planta, tareas, chunksize=chunksize))


def calcular_con_hilos(
    tareas: list[tuple[str, list[float], int]], max_workers: int | None = None
) -> list[dict[str, Any]]:
    """Descompone el lote por planta usando hilos."""

    if not tareas:
        return []
    if len(tareas) == 1:
        return calcular_secuencial(tareas)

    workers = _normalizar_workers(max_workers, len(tareas))
    pool = _obtener_thread_pool(workers)
    return list(pool.map(_calcular_una_planta, tareas))


def calcular_distribuido(
    tareas: list[tuple[str, list[float], int]],
    *,
    modo: str = "paralelo",
    max_workers: int | None = None,
    backend: str | None = None,
) -> tuple[str, int, list[dict[str, Any]]]:
    """Selecciona el camino de ejecución y devuelve ``(backend, workers, resultados)``."""

    modo_normalizado = (modo or "paralelo").strip().lower()
    if modo_normalizado not in {"secuencial", "paralelo"}:
        raise ValueError("El modo debe ser 'secuencial' o 'paralelo'.")
    if modo_normalizado == "secuencial" or len(tareas) <= 1:
        return "secuencial", 1, calcular_secuencial(tareas)

    seleccionado = (backend or os.getenv("PARALLEL_BACKEND", "thread")).strip().lower()
    if seleccionado == "auto":
        seleccionado = "thread"
    if seleccionado not in {"thread", "process"}:
        raise ValueError("El backend debe ser 'thread', 'process' o 'auto'.")

    workers = _normalizar_workers(max_workers, len(tareas))
    if seleccionado == "thread":
        return "thread", workers, calcular_con_hilos(tareas, max_workers=workers)
    return "process", workers, calcular_paralelo(tareas, max_workers=workers)


def cerrar_pools() -> None:
    """Cierra los pools reutilizables al terminar el proceso de la API."""

    global _PROCESS_POOL, _PROCESS_WORKERS, _THREAD_POOL, _THREAD_WORKERS
    with _LOCK_POOLS:
        if _PROCESS_POOL is not None:
            _PROCESS_POOL.shutdown(wait=True)
            _PROCESS_POOL = None
            _PROCESS_WORKERS = None
        if _THREAD_POOL is not None:
            _THREAD_POOL.shutdown(wait=True)
            _THREAD_POOL = None
            _THREAD_WORKERS = None


atexit.register(cerrar_pools)
