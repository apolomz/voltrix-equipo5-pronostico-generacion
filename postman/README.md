# Postman — Equipo 5

Colección lista para importar en Postman. Incluye salud, dependencias, contrato,
los tres backends y la consulta del último pronóstico.

## Importar

1. Abrir Postman → **Import**.
2. Arrastrar estos archivos:
   - `Voltrix-Equipo5.postman_collection.json`
   - `Voltrix-Local.postman_environment.json`
   - `Voltrix-EC2.postman_environment.json` (opcional)
3. Seleccionar el environment **Voltrix Local** (o **Voltrix EC2**).
4. Verificar que `base_url` apunte al servicio:
   - Local: `http://localhost:8000`
   - EC2: `http://13.59.129.153:8000`

## Orden recomendado

| Carpeta | Request | Qué muestra |
|---|---|---|
| 00 · Operación | Health | API y base de datos disponibles |
| 00 · Operación | Dependencias | En demo: `no_aplica` para Eq1/2/4 |
| 00 · Operación | OpenAPI YAML | Contrato publicado |
| 01 · Pronósticos | Generar secuencial | Línea base, `workers=1` |
| 01 · Pronósticos | Generar con hilos | `backend=thread`, `workers=2` |
| 01 · Pronósticos | Generar con procesos | `backend=process`, `workers=2` |
| 01 · Pronósticos | Consultar último pronóstico | `GET /pronosticos/PL-001` |
| 01 · Pronósticos | Generar lote de 80 plantas | Escala y `metricas` |

Cada request tiene tests automáticos en la pestaña **Tests**. Al ejecutarlo,
Postman muestra `PASS`/`FAIL` y el `console.log` con backend, workers y
`duracionMs`.

## Configuración manual de una request

Si prefieres crear las requests a mano:

**URL**

```text
{{base_url}}/pronosticos/generar
```

**Query params**

| Key | Value |
|---|---|
| `modo` | `secuencial` o `paralelo` |
| `backend` | `thread` o `process` (solo en paralelo) |
| `workers` | `2` |

**Headers**

| Key | Value |
|---|---|
| `Content-Type` | `application/json` |
| `X-Equipo-Consumidor` | `equipo-6` |
| `X-Request-Id` | `postman-demo-001` |

**Body → raw → JSON**

```json
{
  "planta_ids": ["PL-001", "PL-002", "PL-003"],
  "horizonte_periodos": 6,
  "frecuencia": "hora"
}
```

## Qué revisar en la respuesta

```json
{
  "modo_ejecucion": "paralelo",
  "backend_paralelismo": "thread",
  "origen_datos": "demo",
  "cantidad_plantas": 3,
  "metricas": {
    "modo": "paralelo",
    "workers": 2,
    "elementos": 3,
    "duracionMs": 2
  },
  "advertencia": "Datos simulados por el modo demo; no representan telemetría real."
}
```

Headers de respuesta:

- `X-Modo-Datos: demo`
- `X-Backend-Paralelismo: thread|process|secuencial`
- `X-Workers: 2`
- `X-Request-Id: postman-demo-001`

## Collection Runner

Para ejecutar toda la colección:

1. Clic derecho sobre la colección → **Run collection**.
2. Seleccionar el environment **Voltrix Local**.
3. **Run Voltrix Equipo 5**.

Los tests deben quedar en verde. El request de 80 plantas usa un pre-request
script que genera `PL-001…PL-080`.

## Notas

- La primera llamada con `backend=process` puede tardar cerca de 1 s por el
  arranque del pool; las siguientes son más rápidas.
- En modo demo las plantas válidas son `PL-001…PL-080`.
- En la EC2 actual puede estar la versión anterior hasta que se haga push,
  pull y `docker compose up --build -d`.
- Para mostrar el modo real, levantar `scripts/mock_dependencias.py` y cambiar
  el environment a las URLs del mock; ver `docs/DEMO_JUEVES.md`.
