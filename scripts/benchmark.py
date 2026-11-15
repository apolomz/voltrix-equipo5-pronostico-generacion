"""Benchmark reproducible: NumPy secuencial, ThreadPool y ProcessPool.

Ejecutar desde la raíz:
    python scripts/benchmark.py --plants 80 --samples 30000 --horizon 24 --repeats 7

La primera creación de procesos se reporta por separado. Los tiempos medidos
reutilizan los pools calientes. Guardar la salida JSON como evidencia cruda.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.forecast import calcular_con_hilos, calcular_paralelo, calcular_secuencial


def construir_tareas(numero_plantas: int, numero_muestras: int, horizonte: int):
    rng = np.random.default_rng(42)
    x = np.arange(numero_muestras, dtype=np.float64)
    tareas = []
    for indice in range(numero_plantas):
        pendiente = 0.001 + (indice % 10) * 0.0001
        ruido = rng.normal(0, 0.5, size=numero_muestras)
        historico = (20 + indice + pendiente * x + ruido).tolist()
        tareas.append((f"PLANTA-{indice + 1:03d}", historico, horizonte))
    return tareas


def validar_equivalencia(referencia, candidato, nombre):
    if [r["planta_id"] for r in referencia] != [r["planta_id"] for r in candidato]:
        raise RuntimeError(f"{nombre}: resultados en un orden distinto.")
    for base, paralelo in zip(referencia, candidato):
        if not np.allclose(base["predicciones"], paralelo["predicciones"], rtol=1e-9, atol=1e-9):
            raise RuntimeError(f"{nombre}: resultado distinto para {base['planta_id']}.")


def resumen(tiempos, referencia):
    mediana = statistics.median(tiempos)
    return {
        "tiempos_segundos": [round(x, 6) for x in tiempos],
        "mediana_segundos": round(mediana, 6),
        "minimo_segundos": round(min(tiempos), 6),
        "maximo_segundos": round(max(tiempos), 6),
        "speedup_sobre_secuencial": round(referencia / mediana, 4) if mediana > 0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Compara tres estrategias de ejecución.")
    parser.add_argument("--plants", type=int, default=80)
    parser.add_argument("--samples", type=int, default=30000)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()

    if args.plants < 2 or args.samples < 2 or args.horizon < 1 or args.repeats < 1:
        parser.error("plants y samples deben ser >= 2; horizon y repeats >= 1")

    workers = args.workers or min(int(os.getenv("MAX_WORKERS", "2")), os.cpu_count() or 1, args.plants)
    tareas = construir_tareas(args.plants, args.samples, args.horizon)

    # Calentamiento y coste frío de creación del pool de procesos.
    secuencial_warm = calcular_secuencial(tareas)
    hilos_warm = calcular_con_hilos(tareas, max_workers=workers)
    inicio = time.perf_counter()
    procesos_warm = calcular_paralelo(tareas, max_workers=workers)
    inicio_pool_procesos = time.perf_counter() - inicio
    validar_equivalencia(secuencial_warm, hilos_warm, "ThreadPool")
    validar_equivalencia(secuencial_warm, procesos_warm, "ProcessPool")

    secuenciales, hilos, procesos = [], [], []
    for _ in range(args.repeats):
        inicio = time.perf_counter()
        secuencial = calcular_secuencial(tareas)
        secuenciales.append(time.perf_counter() - inicio)

        inicio = time.perf_counter()
        por_hilos = calcular_con_hilos(tareas, max_workers=workers)
        hilos.append(time.perf_counter() - inicio)

        inicio = time.perf_counter()
        por_procesos = calcular_paralelo(tareas, max_workers=workers)
        procesos.append(time.perf_counter() - inicio)

        validar_equivalencia(secuencial, por_hilos, "ThreadPool")
        validar_equivalencia(secuencial, por_procesos, "ProcessPool")

    mediana_secuencial = statistics.median(secuenciales)
    resultado = {
        "descripcion": "Misma regresión NumPy y mismo conjunto de datos en las tres estrategias.",
        "plantas": args.plants,
        "muestras_por_planta": args.samples,
        "horizonte": args.horizon,
        "repeticiones_medidas": args.repeats,
        "workers_paralelos": workers,
        "arranque_frio_process_pool_segundos": round(inicio_pool_procesos, 6),
        "secuencial": resumen(secuenciales, mediana_secuencial),
        "thread_pool": resumen(hilos, mediana_secuencial),
        "process_pool": resumen(procesos, mediana_secuencial),
        "equivalencia_numerica": "OK: resultados comparados con numpy.allclose",
        "equipo": {
            "sistema_operativo": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "cpu_logicas": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
        },
        "nota": (
            "El speedup es una medición del entorno donde se ejecuta el script. "
            "No atribuir diferencias a GIL, memoria o CPU sin mediciones adicionales."
        ),
    }
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
