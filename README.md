# Voltrix Energy — Equipo 5: Pronóstico de Generación

Microservicio para estimar la generación futura de energía por planta,
desarrollado con Python, FastAPI y NumPy. Incluye descomposición de datos por
planta, experimentos de ejecución secuencial/paralela y despliegue
local contenerizado con Docker Compose.

## Integrantes

| Juan Fernando Duque Jojoa |

| Jhoan Sebastian Fernandez |

| Jean Paul Davalos Valencia |

## Stack

- Python 3.12
- FastAPI + Pydantic
- NumPy para regresión lineal
- `ThreadPoolExecutor` como backend inicial configurable de la API
- `ProcessPoolExecutor` como alternativa paralela experimental de comparación
- Pytest para pruebas
- Docker + Docker Compose para ejecución local contenerizada

## Alcance

- `GET /health`
- `POST /pronosticos/generar`
- `GET /pronosticos/{plantaId}`
- Swagger en `/docs` y contrato OpenAPI en `/openapi.json`.
- Datos simulados y almacenamiento temporal en memoria.
- Benchmark secuencial vs. `ThreadPoolExecutor` vs. `ProcessPoolExecutor`.
- Dockerfile con usuario no-root y chequeo health; DockerCompose con límites locales de memoria/CPU.

> Esta versión no consume demás apis, ni tiene persistencia en base de datos.

## Ejecutar localmente

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000/docs`.

## Ejecutar con Docker Compose

Requisitos: Docker instalado y en ejecución.

```powershell
# Construir la imagen y arrancar el contenedor
docker compose up --build -d

# Verificar estado y healthcheck
docker compose ps

# Consultar logs
docker compose logs -f api

# Vigilar memoria y CPU del contenedor
docker stats voltrix-equipo5-api

# Detener y eliminar el contenedor
docker compose down
```

Al levantarlo:

- Swagger: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>
- Health: <http://localhost:8000/health>

El DockerCompose local arranca solamente la API con `PARALLEL_BACKEND=thread` y dos trabajadores configurados. No se añade un contenedor PostgreSQL

## Probar la API

En Swagger, ejecutar `POST /pronosticos/generar` con:

```json
{
  "planta_ids": ["PLANTA-001", "PLANTA-002", "PLANTA-003"],
  "horizonte_periodos": 6,
  "frecuencia": "hora"
}
```

Luego consultar `GET /pronosticos/PLANTA-001`.

## Ejecutar pruebas

```
pytest -q
```

## Benchmark de paralelismo

El benchmark compara el mismo cálculo y los mismos datos con tres variantes:

1. Secuencial (línea base).
2. `ThreadPoolExecutor` (variante por hilos).
3. `ProcessPoolExecutor` (variante por procesos, seleccionable mediante `PARALLEL_BACKEND=process`).

Ejecutar:

```
python scripts/benchmark.py --plants 80 --samples 30000 --horizon 24 --workers 2 --repeats 7
```

Para cambiar el backend usado por la API, configura `PARALLEL_BACKEND=thread`
o `PARALLEL_BACKEND=process`. En Docker Compose se deja `thread` como valor
inicial, pero el benchmark permite contrastar ambas estrategias.

Se informa el coste de arranque frío del pool de procesos por separado y se
reportan los siete tiempos, mediana, mínimo, máximo, speedup y características
del equipo. El benchmark valida la equivalencia con `numpy.allclose`.

