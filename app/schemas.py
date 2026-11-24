from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Frecuencia(str, Enum):
    HORA = "hora"
    DIA = "dia"


class ModoEjecucion(str, Enum):
    SECUENCIAL = "secuencial"
    PARALELO = "paralelo"


class SolicitudGeneracion(BaseModel):
    """Solicitud para generar pronósticos de una o varias plantas."""

    planta_ids: list[str] = Field(
        min_length=1,
        description="Identificadores de las plantas que se desean pronosticar.",
        examples=[["PL-001", "PL-002"]],
    )
    horizonte_periodos: int = Field(
        default=6,
        ge=1,
        le=168,
        description="Cantidad de periodos futuros que se desean estimar.",
        examples=[6],
    )
    frecuencia: Frecuencia = Field(
        default=Frecuencia.HORA,
        description="Resolución temporal del pronóstico.",
    )
    desde: datetime | None = Field(
        default=None,
        description="Inicio opcional del rango histórico (RFC 3339 con zona horaria).",
    )
    hasta: datetime | None = Field(
        default=None,
        description="Fin opcional del rango histórico (RFC 3339 con zona horaria).",
    )


class PuntoPronostico(BaseModel):
    periodo: datetime
    generacion_kwh: float = Field(ge=0)


class PronosticoPlanta(BaseModel):
    planta_id: str
    metodo: Literal["regresion_lineal"] = "regresion_lineal"
    frecuencia: Frecuencia
    generado_en: datetime
    valores: list[PuntoPronostico]


class MetricasProcesamiento(BaseModel):
    modo: ModoEjecucion
    workers: int = Field(ge=1)
    elementos: int = Field(ge=0)
    duracionMs: int = Field(ge=0)


class RespuestaGeneracion(BaseModel):
    modo_ejecucion: ModoEjecucion
    backend_paralelismo: Literal["secuencial", "thread", "process"]
    origen_datos: str = "demo"
    cantidad_plantas: int
    pronosticos: list[PronosticoPlanta]
    metricas: MetricasProcesamiento
    advertencia: str = (
        "Prototipo académico: se usan datos simulados. La integración real con "
        "Inventario, Telemetría y Reportes está pendiente de acordar sus contratos."
    )


class RespuestaSalud(BaseModel):
    estado: Literal["disponible", "no_disponible"] = "disponible"
    baseDatos: Literal["ok", "error"] = "ok"
    version: str = "1.0.0"
    tiempoActivoSeg: int = Field(ge=0)


class DetalleError(BaseModel):
    campo: str
    problema: str


class ErrorResponse(BaseModel):
    codigo: str
    mensaje: str
    requestId: str
    detalles: list[DetalleError] | None = None