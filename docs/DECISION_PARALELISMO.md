# Diseño de paralelismo — Equipo 5

## Unidad de descomposición

El trabajo se descompone por planta. Cada tarea recibe el identificador de una
planta, su serie histórica y el horizonte que debe pronosticar. Las tareas no
comparten matrices mutables ni dependen del resultado de otra planta.

```text
Lote de plantas
   ├── Planta 001 ──> NumPy / regresión lineal ──> pronóstico 001
   ├── Planta 002 ──> NumPy / regresión lineal ──> pronóstico 002
   ├── Planta 003 ──> NumPy / regresión lineal ──> pronóstico 003
   └── Planta N   ──> NumPy / regresión lineal ──> pronóstico N
                                      │
                              consolidar respuestas
```

## Uso

| Descomposición de dominio por bloques de filas |
| NumPy | Se reutiliza para representar series numéricas y calcular la regresión lineal (`numpy.polyfit`). |
| Medición de varias ejecuciones, mediana y rango |
| Comparar versión base y paralela con resultados equivalentes |

## ¿Hilos o procesos?

La implementación permite comparar tres alternativas con el mismo conjunto de
series y el mismo algoritmo. La API puede cambiar entre los dos backends paralelos
por variable de entorno:

1. Secuencial: línea base.
2. `ThreadPoolExecutor`: reparte plantas entre hilos y evita serializar cada
   tarea entre procesos. NumPy ejecuta parte del trabajo en bibliotecas nativas,
   pero la mejora real debe medirse; no se presupone.
3. `ProcessPoolExecutor`: reparte plantas entre procesos independientes. Es una
   forma explícita de paralelismo, pero añade coste de arranque, serialización y
   memoria por proceso.

El servicio permite seleccionar el backend mediante `PARALLEL_BACKEND=thread`
o `PARALLEL_BACKEND=process`, con `MAX_WORKERS` configurable. Se selecciona
inicialmente `ThreadPoolExecutor` para Docker porque evita serializar cada tarea
y crear intérpretes adicionales. En una medición preliminar sintética del entorno
de desarrollo, los hilos superaron ligeramente a los procesos; esto no sustituye
la medición en los equipos del grupo. Para la instancia EC2 limitada a 1 GiB, la
selección debe considerar tanto el tiempo como el consumo de memoria; no se debe
elegir únicamente por el speedup local.

## Sincronización y seguridad

Cada tarea lee su propia serie y devuelve un resultado nuevo. No escribe en un
buffer compartido. La operación `executor.map` espera a que finalicen las tareas
y entrega los resultados para su consolidación. Por ello no se requiere una
barrera explícita ni doble búfer. El orden de los resultados se conserva según
el orden de entrada de `map`.

## Protocolo experimental

Ejecutar desde la raíz del repositorio:

```bash
python scripts/benchmark.py --plants 80 --samples 30000 --horizon 24 --workers 2 --repeats 7
```

El script:

- usa exactamente los mismos datos y el mismo cálculo en las tres estrategias;
- separa el arranque frío del `ProcessPoolExecutor` de las mediciones con el pool reutilizado;
- registra los siete tiempos individuales, mediana, mínimo, máximo y speedup;
- comprueba equivalencia numérica con `numpy.allclose`;
- registra sistema operativo, versión de Python y NumPy, CPU lógicas y RAM total.

Guardar la salida completa como evidencia, por ejemplo:

```bash
python scripts/benchmark.py --plants 80 --samples 30000 --horizon 24 --workers 2 --repeats 7 > benchmarks/benchmark_$(date +%Y%m%d_%H%M%S).json
```

El resultado depende del equipo. Informar el efecto medido, no atribuirlo a
saturación de memoria, GIL u otra causa sin una medición específica.
