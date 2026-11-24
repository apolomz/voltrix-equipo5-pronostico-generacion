# Contrato API propuesto — Equipo 5

Base path: `/`
Versión inicial: `0.1.0`
Formato: JSON

## GET /health

Respuesta 200:

```json
{
  "status": "ok",
  "servicio": "pronostico-generacion"
}
```

## POST /pronosticos/generar

Propósito: solicitar pronósticos para una o varias plantas. El servicio debe obtener y validar los datos históricos mediante sus dependencias (Inventario, Telemetría y Reportes); en el prototipo inicial usa datos simulados.

Solicitud:

```json
{
  "planta_ids": ["PLANTA-001", "PLANTA-002"],
  "horizonte_periodos": 6,
  "frecuencia": "hora"
}
```

Reglas:

- `planta_ids`: lista no vacía de identificadores.
- `backend_paralelismo`: backend usado en la ejecución (`thread`, `process` o `secuencial`).
- `horizonte_periodos`: entero entre 1 y 168.
- `frecuencia`: `hora` o `dia`.

Respuesta 200 (ejemplo abreviado):

```json
{
  "modo_ejecucion": "paralelo",
  "backend_paralelismo": "thread",
  "origen_datos": "demo",
  "cantidad_plantas": 2,
  "pronosticos": [
    {
      "planta_id": "PLANTA-001",
      "metodo": "regresion_lineal",
      "frecuencia": "hora",
      "generado_en": "2026-11-15T17:00:00Z",
      "valores": [
        {
          "periodo": "2026-11-15T18:00:00Z",
          "generacion_kwh": 40.2
        }
      ]
    }
  ],
  "advertencia": "Prototipo académico: se usan datos simulados..."
}
```

## GET /pronosticos/{plantaId}

Propósito: consultar el último pronóstico generado para una planta.

Respuesta 200: objeto `PronosticoPlanta` (mismo esquema del elemento de `pronosticos`).

Respuesta 404: no existe un pronóstico para el identificador solicitado.

## Decisiones pendientes de validar

El caso de estudio define las rutas mínimas, pero no fija todos los campos de entrada/salida. Validar con el profesor y equipos proveedores: unidades, frecuencia, horizonte, formato temporal, identificadores y contrato de las dependencias. El contrato servido por FastAPI en `/openapi.json` es la fuente ejecutable de esta versión.
