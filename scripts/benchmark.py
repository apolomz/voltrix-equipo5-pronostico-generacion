"""Benchmark reproducible: NumPy secuencial, ThreadPool y ProcessPool.

Barre varias cantidades de plantas y varios números de workers en una sola
corrida. Ejecutar desde la raíz del repositorio:

    python scripts/benchmark.py --plants 40 80 --workers 1 2 4 8 --repeats 7 \
        --cpu-name "Intel Core i5-1135G7" --output benchmarks/benchmark_rivera.json

Criterios de medición:
* Para cada cantidad de plantas, la línea base secuencial se mide una vez.
* Para cada número de workers se recrean los pools y se hace un calentamiento
  antes de medir. El arranque frío del ProcessPool (spawn) se reporta aparte.
* ``forecast.py`` limita los workers a ``os.cpu_count()`` y al número de
  plantas; aquí se usan los workers EFECTIVOS y se omiten los repetidos.
* Cada repetición valida equivalencia numérica con ``numpy.allclose``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.forecast import (
    calcular_con_hilos,
    calcular_paralelo,
    calcular_secuencial,
    cerrar_pools,
)


def construir_tareas(numero_plantas: int, numero_muestras: int, horizonte: int, semilla: int):
    rng = np.random.default_rng(semilla)
    x = np.arange(numero_muestras, dtype=np.float64)
    tareas = []
    for indice in range(numero_plantas):
        pendiente = 0.001 + (indice % 10) * 0.0001
        ruido = rng.normal(0, 0.5, size=numero_muestras)
        historico = (20 + indice + pendiente * x + ruido).tolist()
        tareas.append((f"PL-{indice + 1:03d}", historico, horizonte))
    return tareas


def validar_equivalencia(referencia, candidato, nombre):
    if [r["planta_id"] for r in referencia] != [r["planta_id"] for r in candidato]:
        raise RuntimeError(f"{nombre}: resultados en un orden distinto.")
    for base, paralelo in zip(referencia, candidato):
        if not np.allclose(base["predicciones"], paralelo["predicciones"], rtol=1e-9, atol=1e-9):
            raise RuntimeError(f"{nombre}: resultado distinto para {base['planta_id']}.")


def medir(funcion, tareas, workers=None):
    inicio = time.perf_counter()
    if workers is None:
        resultado = funcion(tareas)
    else:
        resultado = funcion(tareas, max_workers=workers)
    return time.perf_counter() - inicio, resultado


def estadisticas(tiempos, referencia=None, workers=None):
    mediana = statistics.median(tiempos)
    datos = {
        "tiempos_segundos": [round(x, 6) for x in tiempos],
        "mediana_segundos": round(mediana, 6),
        "minimo_segundos": round(min(tiempos), 6),
        "maximo_segundos": round(max(tiempos), 6),
    }
    if referencia is not None:
        speedup = referencia / mediana if mediana > 0 else None
        datos["speedup_sobre_secuencial"] = round(speedup, 4) if speedup else None
        if speedup and workers:
            datos["eficiencia"] = round(speedup / workers, 4)
    return datos


def resolver_workers(solicitados, plantas):
    """Devuelve {workers_efectivos: workers_solicitados} sin repetidos."""
    limite = min(os.cpu_count() or 1, plantas)
    resultado = {}
    for pedido in solicitados:
        efectivo = max(1, min(pedido, limite))
        resultado.setdefault(efectivo, pedido)
    return resultado


def nombre_cpu(manual: str | None) -> str:
    if manual:
        return manual
    try:
        sistema = platform.system()
        if sistema == "Linux":
            for linea in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if linea.lower().startswith("model name"):
                    return linea.split(":", 1)[1].strip()
        elif sistema == "Darwin":
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        elif sistema == "Windows":
            salida = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                text=True,
            )
            lineas = [linea.strip() for linea in salida.splitlines() if linea.strip()]
            if lineas:
                return lineas[0]
    except Exception:
        pass
    return platform.processor() or "desconocido (use --cpu-name)"


def info_equipo(cpu_manual: str | None) -> dict:
    memoria = psutil.virtual_memory()
    return {
        "sistema_operativo": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "cpu_modelo": nombre_cpu(cpu_manual),
        "cpu_fisicas": psutil.cpu_count(logical=False),
        "cpu_logicas": psutil.cpu_count(logical=True),
        "ram_total_gb": round(memoria.total / (1024**3), 2),
        "ram_disponible_gb": round(memoria.available / (1024**3), 2),
    }


def benchmark_plantas(plantas, args):
    tareas = construir_tareas(plantas, args.samples, args.horizon, args.seed)

    calcular_secuencial(tareas)  # calentamiento de NumPy/caché
    secuenciales = []
    referencia = None
    for _ in range(args.repeats):
        tiempo, referencia = medir(calcular_secuencial, tareas)
        secuenciales.append(tiempo)
    mediana_secuencial = statistics.median(secuenciales)

    configuraciones = []
    for efectivo, pedido in resolver_workers(args.workers, plantas).items():
        if efectivo != pedido:
            print(
                f"[aviso] {plantas} plantas: workers={pedido} limitado a {efectivo} "
                f"(núcleos={os.cpu_count()}, plantas={plantas}).",
                file=sys.stderr,
            )

        # Pools nuevos para este número de workers; el cierre no entra en el tiempo.
        cerrar_pools()
        _, hilos_warm = medir(calcular_con_hilos, tareas, efectivo)
        frio, procesos_warm = medir(calcular_paralelo, tareas, efectivo)
        validar_equivalencia(referencia, hilos_warm, "ThreadPool")
        validar_equivalencia(referencia, procesos_warm, "ProcessPool")

        hilos, procesos = [], []
        for _ in range(args.repeats):
            tiempo, por_hilos = medir(calcular_con_hilos, tareas, efectivo)
            hilos.append(tiempo)
            tiempo, por_procesos = medir(calcular_paralelo, tareas, efectivo)
            procesos.append(tiempo)
            validar_equivalencia(referencia, por_hilos, "ThreadPool")
            validar_equivalencia(referencia, por_procesos, "ProcessPool")

        configuraciones.append(
            {
                "workers_solicitados": pedido,
                "workers_efectivos": efectivo,
                "arranque_frio_process_pool_segundos": round(frio, 6),
                "thread_pool": estadisticas(hilos, mediana_secuencial, efectivo),
                "process_pool": estadisticas(procesos, mediana_secuencial, efectivo),
            }
        )

    return {
        "plantas": plantas,
        "secuencial": estadisticas(secuenciales),
        "configuraciones": configuraciones,
    }


def imprimir_tabla(bloque):
    sec = bloque["secuencial"]["mediana_segundos"]
    print(f"\n=== {bloque['plantas']} plantas | secuencial: {sec:.4f} s (mediana) ===")
    print(f"{'workers':>8} {'hilos (s)':>10} {'speedup':>8} {'procesos (s)':>13} {'speedup':>8} {'arranque frío (s)':>18}")
    for cfg in bloque["configuraciones"]:
        h, p = cfg["thread_pool"], cfg["process_pool"]
        print(
            f"{cfg['workers_efectivos']:>8} {h['mediana_segundos']:>10.4f} "
            f"{h['speedup_sobre_secuencial']:>8.2f} {p['mediana_segundos']:>13.4f} "
            f"{p['speedup_sobre_secuencial']:>8.2f} {cfg['arranque_frio_process_pool_segundos']:>18.3f}"
        )


def main():
    parser = argparse.ArgumentParser(description="Compara tres estrategias de ejecución.")
    parser.add_argument("--plants", type=int, nargs="+", default=[40, 80])
    parser.add_argument("--samples", type=int, default=30000)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cpu-name", type=str, default=None, help="Modelo de CPU si no se detecta.")
    parser.add_argument("--output", type=str, default=None, help="Ruta del JSON de evidencia.")
    args = parser.parse_args()

    if min(args.plants) < 2 or args.samples < 2 or args.horizon < 1 or args.repeats < 1:
        parser.error("plants y samples deben ser >= 2; horizon y repeats >= 1")
    if min(args.workers) < 1:
        parser.error("workers debe ser >= 1")

    equipo = info_equipo(args.cpu_name)
    print(
        f"Equipo: {equipo['cpu_modelo']} | {equipo['cpu_fisicas']} núcleos físicos / "
        f"{equipo['cpu_logicas']} lógicos | {equipo['ram_total_gb']} GB RAM | "
        f"{equipo['sistema_operativo']}",
        file=sys.stderr,
    )

    resultados = []
    try:
        for plantas in args.plants:
            bloque = benchmark_plantas(plantas, args)
            resultados.append(bloque)
            imprimir_tabla(bloque)
    finally:
        cerrar_pools()

    resultado = {
        "descripcion": "Misma regresión NumPy y mismo conjunto de datos en las tres estrategias.",
        "parametros": {
            "plantas": args.plants,
            "workers_solicitados": args.workers,
            "muestras_por_planta": args.samples,
            "horizonte": args.horizon,
            "repeticiones_medidas": args.repeats,
            "semilla": args.seed,
        },
        "equipo": equipo,
        "resultados": resultados,
        "equivalencia_numerica": "OK: resultados comparados con numpy.allclose",
        "nota": (
            "El speedup es una medición del entorno donde se ejecuta el script. "
            "No atribuir diferencias a GIL, memoria o CPU sin mediciones adicionales."
        ),
    }
    if args.output:
        destino = Path(args.output)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nEvidencia escrita en {destino}", file=sys.stderr)


if __name__ == "__main__":
    main()