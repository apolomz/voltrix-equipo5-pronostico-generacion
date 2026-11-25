# Capa de entrada de datos

El servicio normaliza tres fuentes externas y una fuente demo. Toda la
configuración entra por variables de entorno; ninguna URL está quemada en el
código.

## Fuentes

| Equipo | Servicio | Operaciones que usa el Equipo 5 | Datos que extrae |
|---|---|---|---|
| 1 | Inventario de Activos | `GET /plantas`, `GET /plantas/{plantaId}`, `GET /activos?plantaId=` | Existencia y estado de la planta; activos y estado operativo |
| 2 | Telemetría de Plantas | `GET /telemetria/{plantaId}` | `fechaHora`, `metrica`, `valor`, `unidad`; se agregan a kWh |
| 4 | Reportes de Generación | `GET /reportes/generacion` y, opcionalmente, `POST /reportes/generar` | `periodoInicio`, `energiaKwh`, `granularidad` |
| — | Demo | Generador local | Serie determinista por planta |

## Precedencia en modo real

1. **Inventario** valida que cada `planta_id` exista. Si `VALIDAR_ACTIVOS=true`,
   también consulta `GET /activos?plantaId=` y agrega advertencias si no hay
   activos o si todos están fuera de servicio.
2. **Reportes** entrega el histórico por planta con granularidad `hora` o `dia`.
   Se pagina con `limit=200`/`offset`. El rango se interpreta como
   `desde <= periodo < hasta`.
3. Si Reportes devuelve vacío y `REPORTES_GENERAR_SI_VACIO=true`, se hace un
   único `POST /reportes/generar` para las plantas faltantes y se reintenta el
   `GET`.
4. Si sigue vacío, **Telemetría** entrega lecturas. Las de `metrica=potencia`
   se convierten a kWh: promedio de potencia del periodo × horas del periodo.
   Las de `metrica=energia` o unidad `kWh` se suman directamente.
5. Si sigue vacío y `DEMO_FALLBACK=true`, se completa con el generador demo y
   `origen_datos` pasa a `mixto`.

Si no hay datos para ninguna planta, la API responde `502` con
`codigo: DATOS_NO_DISPONIBLES`.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `DEMO_MODE` | `true` | No llama a otros equipos; usa el generador local |
| `DEMO_PLANTAS` | `80` | Tamaño del catálogo demo (`PL-001…PL-080`) |
| `DEMO_DIAS` | `30` | Días de histórico cuando no se envían `desde`/`hasta` |
| `DEMO_FALLBACK` | `false` | Completa con demo las plantas sin datos reales |
| `INVENTARIO_URL` | — | URL base del Equipo 1 |
| `TELEMETRIA_URL` | — | URL base del Equipo 2 |
| `REPORTES_URL` | — | URL base del Equipo 4 |
| `HTTP_TIMEOUT` | `5` | Timeout por llamada, en segundos |
| `HTTP_RETRIES` | `2` | Reintentos ante timeout, 429 o 5xx |
| `FETCH_WORKERS` | `8` | Hilos para descargar datos de varias plantas |
| `MAX_RANGO_DIAS` | `31` | Rango máximo `desde`-`hasta` |
| `MAX_PAGINAS` | `50` | Tope de páginas por fuente |
| `VALIDAR_ACTIVOS` | `true` | Consulta los activos de cada planta en Inventario |
| `REPORTES_GENERAR_SI_VACIO` | `false` | Intenta `POST /reportes/generar` si no hay agregados |

## Comportamiento HTTP

- Todas las llamadas salientes llevan `X-Equipo-Consumidor: equipo-5`.
- Se propaga el `X-Request-Id` de la petición entrante; si no viene, se genera
  un UUID.
- Se reintenta ante `429` respetando `Retry-After` (máximo 5 s) y ante `5xx`
  con backoff exponencial acotado.
- Un `4xx` de una dependencia se reporta como `DEPENDENCIA_FALLIDA` (`502`).
- Los logs registran `upstream`, operación, estado, duración, intento y
  `request_id`.

## Supuestos sobre el contrato del Equipo 1

El contrato publicado del Equipo 1 solo estaba disponible como PDF resumen, sin
esquemas de respuesta. El adaptador acepta:

- listas directas o páginas `{datos: [...], total, limit, offset}`;
- `id`, `plantaId` o `planta_id` para el identificador de planta;
- `tipo`/`tipoActivo`, `estado`/`estadoOperativo`, `capacidadNominalKw`/`capacidadKw`.

Cuando el Equipo 1 publique su `openapi.yaml`, se reemplaza el parseo tolerante
por modelos exactos. El punto único de cambio es
`app/sources/inventario.py`.

## Mock local

`scripts/mock_dependencias.py` levanta una API en el puerto 9000 con los
prefijos `/eq1`, `/eq2` y `/eq4`:

```bash
python scripts/mock_dependencias.py
```

```text
INVENTARIO_URL=http://127.0.0.1:9000/eq1
TELEMETRIA_URL=http://127.0.0.1:9000/eq2
REPORTES_URL=http://127.0.0.1:9000/eq4
```

El mock usa el mismo generador demo, de modo que los IDs y las series son
coherentes. No sustituye una prueba contra los despliegues reales: sirve para
verificar los adaptadores y la precedencia mientras esos servicios terminan sus
avances.

## Pruebas de integración

Los tests de `tests/test_sources.py` usan `httpx.MockTransport` para simular:

- Inventario con plantas y activos;
- Reportes con agregados horarios;
- Telemetría con lecturas de potencia;
- fallback de Reportes a Telemetría;
- planta desconocida y configuración incompleta;
- reintento `503` y propagación de headers;
- paginación por `X-Next-Offset`.
