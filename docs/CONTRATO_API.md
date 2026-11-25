# Contrato API — Equipo 5

Base path: `/`
Versión: `1.0.0`
Formato: JSON
Contrato publicado: <https://apolomz.github.io/voltrix-equipo5-pronostico-generacion/>
Contrato ejecutable: `GET /openapi.yaml` y `GET /openapi.json`

## Endpoints

### `POST /pronosticos/generar`

Genera pronósticos para una o varias plantas.

Query params:

| Parámetro | Valores | Descripción |
|---|---|---|
| `modo` | `secuencial` \| `paralelo` | Línea base o descomposición por planta. Default `paralelo`. |
| `backend` | `auto` \| `thread` \| `process` | Backend paralelo. `auto` usa `PARALLEL_BACKEND`. |
| `workers` | 1…64 | Workers del backend paralelo. |

Solicitud:

```json
{
  "planta_ids": ["PL-001", "PL-002"],
  "horizonte_periodos": 6,
  "frecuencia": "hora",
  "desde": "2026-11-01T00:00:00-05:00",
  "hasta": "2026-11-18T23:59:59-05:00"
}
```

También se aceptan los alias `plantaIds` y `horizontePeriodos`.

Reglas:

- `planta_ids`: lista no vacía de identificadores.
- `horizonte_periodos`: entero entre 1 y 168.
- `frecuencia`: `hora` o `dia`.
- `desde`/`hasta`: RFC 3339 con zona horaria; `desde < hasta`; `hasta` es exclusivo; máximo 31 días.
- En modo demo, las plantas válidas son `PL-001…PL-080`.
- En modo real, las plantas se validan contra Inventario de Activos.

Respuesta 200:

```json
{
  "modo_ejecucion": "paralelo",
  "backend_paralelismo": "thread",
  "origen_datos": "demo",
  "cantidad_plantas": 2,
  "pronosticos": [
    {
      "planta_id": "PL-001",
      "metodo": "regresion_lineal",
      "frecuencia": "hora",
      "generado_en": "2026-11-25T16:00:00Z",
      "valores": [
        {"periodo": "2026-11-25T17:00:00Z", "generacion_kwh": 41.9612}
      ]
    }
  ],
  "metricas": {
    "modo": "paralelo",
    "workers": 2,
    "elementos": 2,
    "duracionMs": 3
  },
  "advertencia": "Datos simulados por el modo demo; no representan telemetría real."
}
```

Headers de respuesta útiles para la evidencia:

- `X-Request-Id`
- `X-Modo-Datos: demo | dependencias | mixto`
- `X-Backend-Paralelismo: secuencial | thread | process`
- `X-Workers`

### `GET /pronosticos/{plantaId}`

Devuelve el último pronóstico guardado para la planta. Responde `404` con
`codigo: NO_ENCONTRADO` si no existe.

### `GET /dependencias/estado`

Comprueba `/health` de Inventario, Telemetría y Reportes. En modo demo devuelve
`no_aplica` para las tres fuentes. No genera pronósticos.

### `GET /health`

```json
{
  "estado": "disponible",
  "baseDatos": "ok",
  "version": "1.0.0",
  "tiempoActivoSeg": 3600
}
```

Responde `503` si PostgreSQL no está disponible.

### `GET /openapi.yaml`

Descarga este contrato en YAML.

## Errores

Esquema común:

```json
{
  "codigo": "DEPENDENCIA_FALLIDA",
  "mensaje": "Inventario de Activos respondió 503",
  "requestId": "3c6e9f2a-8b1d-4e7c-a5f0-6d2b9e1c4a7f",
  "detalles": [
    {"campo": "equipo-1", "problema": "GET /plantas: Inventario de Activos respondió 503"}
  ]
}
```

| HTTP | Código | Cuándo |
|---|---|---|
| 400 | `SOLICITUD_INVALIDA` | Body, fechas o rango inválidos |
| 400 | `RANGO_INVALIDO` | `desde >= hasta` o rango > 31 días |
| 400 | `SERIE_INVALIDA` | Una serie tiene menos de 2 observaciones |
| 404 | `NO_ENCONTRADO` | No hay pronóstico para la planta |
| 404 | `PLANTA_NO_ENCONTRADA` | La planta no existe en Inventario |
| 429 | `SOBRECARGA` | Se agotó la admisión concurrente; incluye `Retry-After` |
| 502 | `DEPENDENCIA_FALLIDA` | Una API de otro equipo falló |
| 502 | `DATOS_NO_DISPONIBLES` | No hay histórico en Reportes ni Telemetría |
| 503 | `NO_DISPONIBLE` | PostgreSQL no responde |
| 503 | `CONFIGURACION_INCOMPLETA` | Falta una URL en modo real |
| 500 | `ERROR_INTERNO` | Error no controlado |

## Trazabilidad

Cada petición entrante recibe o conserva `X-Request-Id`. Las llamadas salientes
llevan:

```text
X-Equipo-Consumidor: equipo-5
X-Request-Id: <el mismo de la petición entrante>
```

Los logs del servicio registran `request_id`, consumidor, ruta, estado y
duración; las llamadas a otros equipos registran equipo, operación, estado,
duración e intento.
