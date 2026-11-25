"""API FastAPI del servicio de Pronóstico de Generación (Equipo 5)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import threading
import time
import uuid

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import httpx

from . import forecast, store
from .config import Config
from .schemas import (
    BackendEjecucion,
    DetalleError,
    ErrorResponse,
    EstadoFuente,
    ModoEjecucion,
    PronosticoPlanta,
    RespuestaDependencias,
    RespuestaGeneracion,
    RespuestaSalud,
    SolicitudGeneracion,
)
from .services import generar_pronosticos
from .sources import DataInputService
from .sources.errors import ErrorDatos

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("voltrix.equipo5")

INICIO_SERVICIO = time.monotonic()
OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.yaml"

# Semáforo para proteger memoria en EC2 (1 GiB RAM) ante ráfagas concurrentes.
MAX_CONCURRENT_REQUESTS = max(1, int(os.getenv("MAX_CONCURRENT_REQUESTS", "1")))
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.inicializar()
    app.state.http_client = httpx.Client(
        timeout=float(os.getenv("HTTP_TIMEOUT", "5")),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    try:
        yield
    finally:
        app.state.http_client.close()
        forecast.cerrar_pools()


app = FastAPI(
    title="Voltrix Energy - Pronóstico de Generación",
    lifespan=lifespan,
    description=(
        "API del Equipo 5 para estimar la generación futura por planta. "
        "Incluye descomposición de datos por planta, ejecución secuencial, "
        "por hilos o por procesos, y una capa de entrada de datos con modo demo "
        "y clientes para Inventario, Telemetría y Reportes."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Operación", "description": "Salud del servicio, contrato y dependencias."},
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


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _detalles(detalles: list[dict] | None) -> list[DetalleError] | None:
    if not detalles:
        return None
    return [
        DetalleError(
            campo=str(detalle.get("campo", "")),
            problema=str(detalle.get("problema", "")),
        )
        for detalle in detalles
    ]


@app.exception_handler(ServiceError)
async def manejar_service_error(request: Request, exc: ServiceError) -> JSONResponse:
    cuerpo = ErrorResponse(
        codigo=exc.codigo,
        mensaje=exc.mensaje,
        requestId=_request_id(request),
        detalles=exc.detalles,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=cuerpo.model_dump(exclude_none=True),
        headers=exc.headers,
    )


@app.exception_handler(ErrorDatos)
async def manejar_error_datos(request: Request, exc: ErrorDatos) -> JSONResponse:
    cuerpo = ErrorResponse(
        codigo=exc.codigo,
        mensaje=exc.mensaje,
        requestId=_request_id(request),
        detalles=_detalles(exc.detalles),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=cuerpo.model_dump(exclude_none=True),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def manejar_validacion_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = _request_id(request)
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


@app.exception_handler(Exception)
async def manejar_error_no_controlado(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("request_id=%s error_no_controlado=%s", _request_id(request), exc)
    cuerpo = ErrorResponse(
        codigo="ERROR_INTERNO",
        mensaje="Ocurrió un error interno al procesar la solicitud.",
        requestId=_request_id(request),
    )
    return JSONResponse(status_code=500, content=cuerpo.model_dump(exclude_none=True))


@app.get(
    "/health",
    response_model=RespuestaSalud,
    responses={503: {"model": RespuestaSalud}},
    tags=["Operación"],
)
def health():
    tiempo_activo = int(time.monotonic() - INICIO_SERVICIO)
    db_ok = store.esta_disponible()

    respuesta = RespuestaSalud(
        estado="disponible" if db_ok else "no_disponible",
        baseDatos="ok" if db_ok else "error",
        version="1.0.0",
        tiempoActivoSeg=tiempo_activo,
    )

    if not db_ok:
        return JSONResponse(status_code=503, content=respuesta.model_dump())

    return respuesta


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


@app.get(
    "/dependencias/estado",
    response_model=RespuestaDependencias,
    tags=["Operación"],
    summary="Comprobar la conectividad con Inventario, Telemetría y Reportes",
)
def estado_dependencias(request: Request) -> RespuestaDependencias:
    config = Config.desde_entorno()
    servicio = DataInputService(
        config, http_client=getattr(request.app.state, "http_client", None)
    )
    try:
        fuentes = servicio.estado_dependencias(request_id=_request_id(request))
    finally:
        servicio.cerrar()

    return RespuestaDependencias(
        modoDatos="demo" if config.demo_mode else "real",
        fuentes=[EstadoFuente.model_validate(fuente) for fuente in fuentes],
    )


@app.post(
    "/pronosticos/generar",
    response_model=RespuestaGeneracion,
    status_code=200,
    tags=["Pronósticos"],
    summary="Generar pronósticos para varias plantas",
    responses={
        400: {"description": "Solicitud o rango inválido."},
        404: {"description": "Alguna planta no existe en Inventario."},
        429: {"description": "Sobrecarga; reintentar con Retry-After."},
        502: {"description": "Una dependencia falló o no hay datos disponibles."},
        503: {"description": "Base de datos o configuración no disponible."},
    },
)
def generar_pronosticos_endpoint(
    request: Request,
    response: Response,
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
    backend: BackendEjecucion | None = Query(
        default=None,
        description="Backend paralelo: auto, thread o process. Si se omite, usa PARALLEL_BACKEND.",
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
        config = Config.desde_entorno()
        try:
            respuesta = generar_pronosticos(
                solicitud,
                modo=modo,
                workers=workers,
                backend=backend.value if backend is not None else None,
                request_id=_request_id(request),
                config=config,
                http_client=getattr(request.app.state, "http_client", None),
            )
        except ValueError as exc:
            raise ServiceError(
                status_code=400,
                codigo="SERIE_INVALIDA",
                mensaje=str(exc),
            ) from exc

        response.headers["X-Modo-Datos"] = respuesta.origen_datos.value
        response.headers["X-Backend-Paralelismo"] = respuesta.backend_paralelismo
        response.headers["X-Workers"] = str(respuesta.metricas.workers)
        return respuesta
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


@app.get("/", include_in_schema=False)
def raiz() -> dict:
    return {
        "servicio": "pronostico-generacion",
        "equipo": "equipo-5",
        "docs": "/docs",
        "openapi": "/openapi.yaml",
        "health": "/health",
        "hora": datetime.now(timezone.utc).isoformat(),
    }
