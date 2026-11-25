# Evidencia de benchmark

Archivos generados con `scripts/benchmark.py` en el entorno local de desarrollo:

| Archivo | Plantas | Muestras/planta | Workers | Repeticiones |
|---|---:|---:|---:|---:|
| `benchmark_20261125_wsl_2workers.json` | 80 | 30 000 | 2 | 7 |
| `benchmark_20261125_wsl_8workers.json` | 80 | 100 000 | 8 | 5 |

Entorno:

- WSL2 (Linux 6.18, x86_64), AMD Ryzen 5 5600G, 12 CPU lógicas, 7.2 GB RAM.
- Python 3.10.12, NumPy 2.2.6.

Resultados (mediana):

| Configuración | Secuencial | Hilos | Procesos | Speedup hilos | Speedup procesos |
|---|---:|---:|---:|---:|---:|
| 2 workers, 30k muestras | 0.1343 s | 0.1203 s | 0.1299 s | 1.12× | 1.03× |
| 8 workers, 100k muestras | 0.6324 s | 0.4049 s | 0.2735 s | 1.56× | 2.31× |

Observaciones:

- Con 2 workers y series cortas, el coste de serialización y el arranque del
  pool dominan; la mejora es pequeña pero medible.
- Con 8 workers y series más largas, el cómputo pesa más y el `ProcessPool`
  alcanza 2.31×. Los hilos mejoran 1.56×, consistente con que NumPy libera el
  GIL solo en parte del cálculo.
- El arranque frío del pool de procesos fue de 0.35 s (2 workers) y 0.58 s
  (8 workers). Por eso la API reutiliza el pool entre peticiones.
- En la instancia EC2 de 1 GiB se recomienda `MAX_WORKERS=2` y vigilar memoria;
  cada proceso carga su propio intérprete y NumPy.

Reproducir:

```bash
python scripts/benchmark.py \
  --plants 80 --samples 100000 --horizon 24 \
  --workers 8 --repeats 5 \
  --output benchmarks/benchmark_20261125_wsl_8workers.json
```
