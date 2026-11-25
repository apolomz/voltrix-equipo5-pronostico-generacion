# Diseño de paralelismo — Equipo 5

## Unidad de descomposición

El trabajo se descompone **por planta**. Cada tarea recibe el identificador de
una planta, su serie histórica y el horizonte; produce sus predicciones sin
compartir matrices mutables ni depender del resultado de otra planta.

```text
Lote de plantas
   ├── PL-001 ──> NumPy / regresión lineal ──> pronóstico 001
   ├── PL-002 ──> NumPy / regresión lineal ──> pronóstico 002
   ├── PL-003 ──> NumPy / regresión lineal ──> pronóstico 003
   └── PL-N   ──> NumPy / regresión lineal ──> pronóstico N
                                      │
                              consolidar respuestas
```

La descomposición es de **datos**, no de tareas del modelo: las plantas son
independientes y el resultado de una no altera el de otra.

## Tres caminos equivalentes

| Camino | Implementación | Uso |
|---|---|---|
| Secuencial | `calcular_secuencial` | Línea base para el benchmark |
| Hilos | `ThreadPoolExecutor` | Menos coste de arranque y de serialización; NumPy libera el GIL en parte del cálculo |
| Procesos | `ProcessPoolExecutor` con `spawn` y `chunksize` | Paralelismo real de CPU; añade serialización y memoria por proceso |

La API elige el camino con `modo` y `backend`:

```bash
# Línea base
POST /pronosticos/generar?modo=secuencial

# Hilos
POST /pronosticos/generar?modo=paralelo&backend=thread&workers=2

# Procesos
POST /pronosticos/generar?modo=paralelo&backend=process&workers=2
```

Si `backend` se omite, se usa `PARALLEL_BACKEND=thread|process|auto`.
`workers` se limita a `min(configurado, cpu_count, número de plantas)`.

## Decisiones de implementación

- **Pools reutilizables:** se crean una vez y se reutilizan entre peticiones.
  Así el benchmark distingue el arranque frío del coste en régimen.
- **`chunksize` en procesos:** se agrupan las plantas en bloques para reducir
  el número de pickles y el coste de IPC. El tamaño es
  `max(1, plantas // (workers * 4))`.
- **Lock de creación:** un `threading.Lock` protege la creación/reemplazo de
  los pools si llegan peticiones concurrentes.
- **Sin estado compartido:** cada tarea devuelve un diccionario nuevo. No hay
  buffer compartido ni necesidad de barreras; `executor.map` conserva el orden
  de entrada.
- **Semáforo de admisión:** `MAX_CONCURRENT_REQUESTS` protege la memoria de la
  instancia EC2. Si se agota, la API responde `429` con `Retry-After`.
- **Medición separada:** `MetricasProcesamiento.duracionMs` mide solo el cálculo
  (no la descarga de datos). El tiempo de datos se registra en los logs.

## Protocolo experimental

Ejecutar desde la raíz del repositorio:

```bash
python scripts/benchmark.py \
  --plants 80 --samples 30000 --horizon 24 \
  --workers 2 --repeats 7 \
  --output benchmarks/benchmark_local.json
```

El script:

- usa exactamente los mismos datos y el mismo cálculo en las tres estrategias;
- separa el arranque frío del `ProcessPoolExecutor` de las mediciones con el
  pool reutilizado;
- registra los siete tiempos individuales, mediana, mínimo, máximo y speedup;
- comprueba equivalencia numérica con `numpy.allclose`;
- registra sistema operativo, versión de Python y NumPy, CPU lógicas y RAM.

## Resultados medidos

Entorno: WSL2, AMD Ryzen 5 5600G, 12 CPU lógicas, 7.2 GB RAM, Python 3.10.12,
NumPy 2.2.6. Evidencia completa en `benchmarks/`.

| Configuración | Secuencial | Hilos | Procesos | Speedup hilos | Speedup procesos |
|---|---:|---:|---:|---:|---:|
| 2 workers, 80 plantas × 30k | 0.1343 s | 0.1203 s | 0.1299 s | 1.12× | 1.03× |
| 8 workers, 80 plantas × 100k | 0.6324 s | 0.4049 s | 0.2735 s | 1.56× | 2.31× |

Lectura:

- Con 2 workers y series cortas, el coste de serialización y el arranque del
  pool dominan; la mejora es pequeña pero medible.
- Con 8 workers y series más largas, el cómputo pesa más y el `ProcessPool`
  alcanza 2.31×. Los hilos mejoran 1.56×, consistente con que NumPy libera el
  GIL solo en parte del cálculo.
- El arranque frío del pool de procesos fue de 0.35 s (2 workers) y 0.58 s
  (8 workers). Por eso la API reutiliza el pool.
- En EC2 (1 GiB) se recomienda `MAX_WORKERS=2` y vigilar memoria: cada proceso
  carga su propio intérprete y NumPy.

Los resultados dependen del equipo donde se ejecute el benchmark. No atribuir
una diferencia a GIL, memoria o CPU sin una medición específica.
