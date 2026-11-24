from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import threading
import time
import uuid

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import store
from .demo_data import obtener_historico_demo
from .forecast import calcular_distribuido, calcular_secuencial
from .schemas import (
    DetalleError,
    ErrorResponse,
    Frecuencia,
    MetricasProcesamiento,
    ModoEjecucion,
    PronosticoPlanta,
    PuntoPronostico,
    RespuestaGeneracion,
    RespuestaSalud,
    SolicitudGeneracion,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("voltrix.equipo5")

INICIO_SERVICIO = time.monotonic()
OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.yaml"

# Semáforo para proteger memoria en EC2 (1 GiB RAM) ante ráfagas concurrentes
MAX_CONCURRENT_REQUESTS = max(1, int(os.getenv("MAX_CONCURRENT_REQUESTS", "2")))
_SEMAFORO_GENERACION = threading.Semaphore(MAX_CONCURRENT_REQUESTS)


class ServiceError(Exception):
    """Excepción de negocio/infraestructura alineada con el esquema común Error."""

    def __init__(
        self,
        status_code: int,
        codigo: str,
        mensaje: str,
        detalles: list[DetalleError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles
        self.headers = headers or {}
        super().__init__(mensaje)


app = FastAPI(
    title="Voltrix Energy - Pronóstico de Generación",
    description=(
        "API del Equipo 5 para estimar la generación futura por planta. "
        "Incluye descomposición de datos por planta y control de concurrencia."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Operación", "description": "Salud del servicio y contrato OpenAPI."},
        {"name": "Pronósticos", "description": "Generación y consulta de pronósticos."},
    ],
)


@app.middleware("http")
async def trazabilidad_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    consumidor = request.headers.get("X-Equipo-Consumidor", "no-especificado")
    request.state.request_id = request_id

    inicio = time.perf_counter()
    response = await call_next(request)
    duracion_ms = round((time.perf_counter() - inicio) * 1000, 2)

    response.headers["X-Request-Id"] = request_id
    logger.info(
        "request_id=%s equipo_consumidor=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        consumidor,
        request.method,
        request.url.path,
        response.status_code,
        duracion_ms,
    )
    return response


@app.exception_handler(ServiceError)
async def manejar_service_error(request: Request, exc: ServiceError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    cuerpo = ErrorResponse(
        codigo=exc.codigo,
        mensaje=exc.mensaje,
        requestId=request_id,
        detalles=exc.detalles,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=cuerpo.model_dump(exclude_none=True),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def manejar_validacion_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    detalles = [
        DetalleError(
            campo=".".join(str(loc) for loc in err["loc"] if loc != "body"),
            problema=err["msg"],
        )
        for err in exc.errors()
    ]
    cuerpo = ErrorResponse(
        codigo="SOLICITUD_INVALIDA",
        mensaje="La solicitud no cumple el contrato.",
        requestId=request_id,
        detalles=detalles,
    )
    return JSONResponse(
        status_code=400,
        content=cuerpo.model_dump(exclude_none=True),
    )


@app.get("/health", response_model=RespuestaSalud, tags=["Operación"])
def health() -> RespuestaSalud:
    tiempo_activo = int(time.monotonic() - INICIO_SERVICIO)

    return RespuestaSalud(
        estado="disponible",
        baseDatos="ok",
        version="1.0.0",
        tiempoActivoSeg=tiempo_activo,
    )


@app.get("/openapi.yaml", tags=["Operación"], summary="Descargar contrato OpenAPI en YAML")
def obtener_contrato_yaml() -> Response:
    if not OPENAPI_PATH.exists():
        raise ServiceError(
            status_code=503,
            codigo="NO_DISPONIBLE",
            mensaje="El archivo openapi.yaml no se encuentra disponible en el servidor.",
        )
    contenido = OPENAPI_PATH.read_text(encoding="utf-8")
    return Response(content=contenido, media_type="application/yaml")


@app.post(
    "/pronosticos/generar",
    response_model=RespuestaGeneracion,
    status_code=200,
    tags=["Pronósticos"],
    summary="Generar pronósticos para varias plantas",
)
def generar_pronosticos(
    solicitud: SolicitudGeneracion,
    modo: ModoEjecucion = Query(
        default=ModoEjecucion.PARALELO,
        description="Modo de ejecución: secuencial (línea base) o paralelo.",
    ),
    workers: int | None = Query(
        default=None,
        ge=1,
        le=64,
        description="Cantidad de workers a emplear en modo paralelo.",
    ),
) -> RespuestaGeneracion:
    if not _SEMAFORO_GENERACION.acquire(blocking=False):
        raise ServiceError(
            status_code=429,
            codigo="SOBRECARGA",
            mensaje="El servicio está atendiendo el máximo de peticiones simultáneas.",
            headers={"Retry-After": "1"},
        )

    try:
        frecuencia = solicitud.frecuencia.value
        tareas = []
        historicos_por_planta: dict[str, list[dict]] = {}

        for planta_id in solicitud.planta_ids:
            historico = obtener_historico_demo(planta_id, frecuencia)
            historicos_por_planta[planta_id] = historico
            tareas.append(
                (
                    planta_id,
                    [punto["generacion_kwh"] for punto in historico],
                    solicitud.horizonte_periodos,
                )
            )

        inicio_calculo = time.perf_counter()
        if modo == ModoEjecucion.SECUENCIAL or len(tareas) <= 1:
            resultados = calcular_secuencial(tareas)
            backend = "secuencial"
            modo_efectivo = ModoEjecucion.SECUENCIAL
            workers_usados = 1
        else:
            backend, resultados = calcular_distribuido(tareas, max_workers=workers)
            modo_efectivo = ModoEjecucion.PARALELO
            configurados = workers or int(os.getenv("MAX_WORKERS", "2"))
            nucleos = os.cpu_count() or 1
            workers_usados = max(1, min(configurados, nucleos, len(tareas)))
        duracion_ms = max(0, round((time.perf_counter() - inicio_calculo) * 1000))

        generado_en = datetime.now(timezone.utc)
        paso = timedelta(hours=1) if solicitud.frecuencia == Frecuencia.HORA else timedelta(days=1)
        pronosticos = []

        for resultado in resultados:
            planta_id = resultado["planta_id"]
            ultimo_periodo = historicos_por_planta[planta_id][-1]["periodo"]
            puntos = [
                PuntoPronostico(
                    periodo=ultimo_periodo + paso * (indice + 1),
                    generacion_kwh=valor,
                )
                for indice, valor in enumerate(resultado["predicciones"])
            ]
            pronostico = PronosticoPlanta(
                planta_id=planta_id,
                frecuencia=solicitud.frecuencia,
                generado_en=generado_en,
                valores=puntos,
            )
            store.guardar(pronostico)
            pronosticos.append(pronostico)

        return RespuestaGeneracion(
            modo_ejecucion=modo_efectivo,
            backend_paralelismo=backend,
            cantidad_plantas=len(pronosticos),
            pronosticos=pronosticos,
            metricas=MetricasProcesamiento(
                modo=modo_efectivo,
                workers=workers_usados,
                elementos=len(pronosticos),
                duracionMs=duracion_ms,
            ),
        )
    finally:
        _SEMAFORO_GENERACION.release()


@app.get(
    "/pronosticos/{plantaId}",
    response_model=PronosticoPlanta,
    tags=["Pronósticos"],
    summary="Consultar el último pronóstico de una planta",
)
def consultar_pronostico(plantaId: str) -> PronosticoPlanta:
    pronostico = store.obtener(plantaId)
    if pronostico is None:
        raise ServiceError(
            status_code=404,
            codigo="NO_ENCONTRADO",
            mensaje=f"No existe un pronóstico generado para la planta {plantaId}.",
        )
    return pronostico