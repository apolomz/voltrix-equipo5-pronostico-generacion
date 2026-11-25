# Runbook — demo del jueves (Avance 1)

Objetivo: mostrar el servicio funcionando con datos de ejemplo, los tres
caminos de ejecución y la capa de datos lista para conectarse con los equipos
1, 2 y 4.

## 1. Preparar el entorno

```bash
cd voltrix-equipo5-pronostico-generacion
cp .env.example .env
# Editar .env si se quiere cambiar el puerto o la clave de PostgreSQL.
docker compose up --build -d
docker compose ps
```

Esperar a que `db` y `api` estén `healthy`.

## 2. Verificar salud y contrato

```bash
curl http://localhost:8000/health
curl http://localhost:8000/dependencias/estado
curl http://localhost:8000/openapi.yaml | head
```

En modo demo, `/dependencias/estado` debe devolver `no_aplica` para las tres
fuentes. Swagger: <http://localhost:8000/docs>.

## 3. Generar pronósticos

```bash
curl -X POST "http://localhost:8000/pronosticos/generar?modo=paralelo&backend=thread&workers=2" \
  -H "Content-Type: application/json" \
  -H "X-Equipo-Consumidor: equipo-5" \
  -d '{"planta_ids":["PL-001","PL-002","PL-003"],"horizonte_periodos":6,"frecuencia":"hora"}'
```

Verificar en la respuesta:

- `origen_datos: demo`
- `backend_paralelismo: thread`
- `metricas.duracionMs`
- `pronosticos[].valores` con 6 puntos
- headers `X-Modo-Datos`, `X-Backend-Paralelismo`, `X-Workers`

Repetir con `modo=secuencial` y con `backend=process`. Los valores numéricos
deben ser equivalentes; lo que cambia es el backend y el tiempo.

```bash
curl -X POST "http://localhost:8000/pronosticos/generar?modo=secuencial" \
  -H "Content-Type: application/json" \
  -d '{"planta_ids":["PL-001","PL-002","PL-003"],"horizonte_periodos":6}'

curl -X POST "http://localhost:8000/pronosticos/generar?modo=paralelo&backend=process&workers=2" \
  -H "Content-Type: application/json" \
  -d '{"planta_ids":["PL-001","PL-002","PL-003"],"horizonte_periodos":6}'
```

Consultar el último pronóstico:

```bash
curl http://localhost:8000/pronosticos/PL-001
```

## 4. Smoke test automatizado

```bash
python scripts/smoke_demo.py --base-url http://localhost:8000
```

Debe imprimir `Smoke test OK` y las tres ejecuciones con sus tiempos.

## 5. Benchmark

```bash
python scripts/benchmark.py \
  --plants 80 --samples 30000 --horizon 24 \
  --workers 2 --repeats 7 \
  --output benchmarks/benchmark_local.json
```

Guardar el JSON y anotar en el informe:

- sistema operativo, CPU lógicas y RAM;
- mediana secuencial, con hilos y con procesos;
- speedup;
- workers.

## 6. Evidencia para el Avance 1

Capturar:

1. `docker compose ps` con ambos contenedores `healthy`.
2. `curl /health`.
3. `curl /dependencias/estado`.
4. Una respuesta de `/pronosticos/generar` con `origen_datos: demo`.
5. Los headers `X-Modo-Datos` y `X-Backend-Paralelismo`.
6. `docker stats --no-stream` durante la demo (memoria de API y DB).
7. El JSON del benchmark.

## 7. Modo real con el mock (opcional)

Si se quiere demostrar que los adaptadores ya están listos:

```bash
# Terminal 1
python scripts/mock_dependencias.py

# Terminal 2
DEMO_MODE=false \
INVENTARIO_URL=http://127.0.0.1:9000/eq1 \
TELEMETRIA_URL=http://127.0.0.1:9000/eq2 \
REPORTES_URL=http://127.0.0.1:9000/eq4 \
uvicorn app.main:app --port 8000
```

Luego repetir el `POST /pronosticos/generar` y verificar
`origen_datos: dependencias`.

Si la API corre dentro de Docker y el mock en el host, usa
`http://host.docker.internal:9000/eq1` (y análogos). El `docker-compose.yaml`
ya declara `extra_hosts: host.docker.internal:host-gateway`.

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `503 CONFIGURACION_INCOMPLETA` | `DEMO_MODE=false` y falta una URL | Definir `INVENTARIO_URL`, `TELEMETRIA_URL`, `REPORTES_URL` |
| `502 DATOS_NO_DISPONIBLES` | Reportes y Telemetría sin datos | Activar `DEMO_FALLBACK=true` o revisar las dependencias |
| `429 SOBRECARGA` | `MAX_CONCURRENT_REQUESTS` agotado | Esperar `Retry-After` o subir el límite |
| `404 PLANTA_NO_ENCONTRADA` | ID fuera de `PL-001…PL-080` en demo | Usar un ID del catálogo |
| `process` falla al arrancar en Windows | `spawn` reimporta el módulo principal | Ejecutar con `uvicorn` o desde un archivo, no desde `python -c` |
