# Voltrix Energy — Equipo 5: Pronóstico de Generación

Microservicio para estimar la generación futura de energía por planta. Usa
regresión lineal y **descomposición de datos planta por planta** con tres
caminos de ejecución: secuencial (línea base), hilos y procesos.

Incluye una capa de entrada de datos lista para conectarse con los equipos 1, 2
y 4, y un **modo demo** con 80 plantas simuladas para el Avance 1.

- Contrato publicado: <https://apolomz.github.io/voltrix-equipo5-pronostico-generacion/>
- Swagger local: <http://localhost:8000/docs>

## Integrantes

- Jhoan Sebastian Fernandez
- Juan Fernando Duque Jojoa
- Jean Paul Davalos Valencia

## Stack

- Python 3.12, FastAPI y Pydantic
- NumPy para la regresión lineal
- `ThreadPoolExecutor` y `ProcessPoolExecutor` para el cálculo paralelo
- PostgreSQL 16 para persistencia (con fallback en memoria si no está configurada)
- Docker y Docker Compose
- Pytest y `httpx.MockTransport` para pruebas

## Arquitectura

```text
POST /pronosticos/generar
        │
        ▼
app/sources/service.py  ──►  Inventario (Eq1)  ──► valida plantas/activos
        │                 ├─►  Reportes (Eq4)    ──► agregados históricos
        │                 ├─►  Telemetría (Eq2)  ──► lecturas → kWh
        │                 └─►  demo.py            ──► series simuladas
        ▼
app/forecast.py  ──►  secuencial | hilos | procesos (planta por planta)
        │
        ▼
app/store.py  ──►  PostgreSQL o memoria
```

### Precedencia de datos en modo real

1. **Inventario de Activos** valida que las plantas existan (y opcionalmente sus activos).
2. **Reportes de Generación** entrega los agregados históricos (`energiaKwh`).
3. **Telemetría de Plantas** se usa si Reportes no tiene datos; las lecturas de
   potencia se agregan a kWh por hora o por día.
4. **Demo** solo si `DEMO_FALLBACK=true` y la planta sigue sin datos.

Si una dependencia falla, la API responde `502` con el esquema común `Error`.
Si falta configuración, responde `503`. Si la planta no existe, `404`.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/pronosticos/generar?modo=secuencial\|paralelo&backend=auto\|thread\|process&workers=N` | Genera pronósticos para una o varias plantas |
| `GET` | `/pronosticos/{plantaId}` | Consulta el último pronóstico de una planta |
| `GET` | `/dependencias/estado` | Comprueba la conectividad con los equipos 1, 2 y 4 |
| `GET` | `/health` | Salud de la API y de PostgreSQL |
| `GET` | `/openapi.yaml` | Contrato OpenAPI en YAML |

La solicitud acepta `planta_ids`/`horizonte_periodos` y también los alias
`plantaIds`/`horizontePeriodos` de la plantilla común. Las fechas deben incluir
zona horaria (RFC 3339) y el rango máximo es de 31 días.

## Modo demo (jueves)

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health
python scripts/smoke_demo.py --base-url http://localhost:8000
```

El modo demo no llama a otros equipos. Genera `PL-001…PL-080` con perfiles
solares, eólicos e híbridos deterministas, y devuelve `origen_datos: demo`.

Prueba los tres caminos:

```bash
curl -X POST "http://localhost:8000/pronosticos/generar?modo=secuencial" \
  -H "Content-Type: application/json" \
  -d '{"planta_ids":["PL-001","PL-002"],"horizonte_periodos":6,"frecuencia":"hora"}'

curl -X POST "http://localhost:8000/pronosticos/generar?modo=paralelo&backend=thread&workers=2" \
  -H "Content-Type: application/json" \
  -d '{"planta_ids":["PL-001","PL-002"],"horizonte_periodos":6,"frecuencia":"hora"}'

curl -X POST "http://localhost:8000/pronosticos/generar?modo=paralelo&backend=process&workers=2" \
  -H "Content-Type: application/json" \
  -d '{"planta_ids":["PL-001","PL-002"],"horizonte_periodos":6,"frecuencia":"hora"}'
```

## Modo real y mock local

El mock implementa el subconjunto de los contratos de los equipos 1, 2 y 4 que
consume este servicio:

```bash
# Terminal 1
python scripts/mock_dependencias.py

# Terminal 2
DEMO_MODE=false \
INVENTARIO_URL=http://127.0.0.1:9000/eq1 \
TELEMETRIA_URL=http://127.0.0.1:9000/eq2 \
REPORTES_URL=http://127.0.0.1:9000/eq4 \
uvicorn app.main:app --reload --port 8000
```

Luego:

```bash
curl http://localhost:8000/dependencias/estado
curl -X POST "http://localhost:8000/pronosticos/generar" \
  -H "Content-Type: application/json" \
  -d '{"planta_ids":["PL-001"],"horizonte_periodos":6}'
```

En EC2, reemplaza las URLs por las de la hoja `Coordinacion_Voltrix`. No las
escribas en el código: van en `.env` o en el ConfigMap.

## Pruebas

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

## Benchmark de paralelismo

```bash
python scripts/benchmark.py \
  --plants 80 --samples 30000 --horizon 24 --workers 2 --repeats 7 \
  --output benchmarks/benchmark_local.json
```

El script mide el mismo cálculo con secuencial, hilos y procesos, verifica
equivalencia con `numpy.allclose` y reporta mediana, mínimo, máximo, speedup y
características del equipo. Ver [`docs/DECISION_PARALELISMO.md`](docs/DECISION_PARALELISMO.md).

## Estructura

```text
app/
  config.py            variables de entorno
  forecast.py          motor secuencial/hilos/procesos
  main.py              API y manejo de errores
  schemas.py           contrato Pydantic
  store.py             PostgreSQL o memoria
  sources/             capa de entrada de datos
    demo.py            generador determinista
    http.py            cliente con reintentos y trazabilidad
    inventario.py      Equipo 1
    telemetria.py      Equipo 2
    reportes.py        Equipo 4
    service.py         precedencia y orquestación
  services/
    pronostico.py      caso de uso
scripts/
  benchmark.py
  mock_dependencias.py
  smoke_demo.py
tests/
docs/
```

## Despliegue

El despliegue EC2 y Floci EKS lo mantiene otro integrante del equipo. Este
repositorio deja el `docker-compose.yaml` con límites de memoria para la
instancia de 1 GiB, healthcheck y variables para el modo demo o real.

## Nota sobre los contratos externos

El contrato del Equipo 1 solo estaba disponible como PDF resumen, sin esquemas
de respuesta. `app/sources/inventario.py` acepta las variantes habituales
(`id`/`plantaId`, `datos`/`data`) y se ajustará cuando se publique su
`openapi.yaml`.
