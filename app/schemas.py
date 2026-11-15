from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Frecuencia(str, Enum):
    HORA = "hora"
    DIA = "dia"


class SolicitudGeneracion(BaseModel):
    """Solicitud para generar pronósticos de una o varias plantas."""

    planta_ids: list[str] = Field(
        min_length=1,
        description="Identificadores de las plantas que se desean pronosticar.",
        examples=[["PLANTA-001", "PLANTA-002"]],
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


class PuntoPronostico(BaseModel):
    periodo: datetime
    generacion_kwh: float = Field(ge=0)


class PronosticoPlanta(BaseModel):
    planta_id: str
    metodo: Literal["regresion_lineal"] = "regresion_lineal"
    frecuencia: Frecuencia
    generado_en: datetime
    valores: list[PuntoPronostico]


class RespuestaGeneracion(BaseModel):
    modo_ejecucion: Literal["paralelo", "secuencial_por_una_planta"]
    backend_paralelismo: Literal["secuencial", "thread", "process"]
    origen_datos: Literal["demo"] = "demo"
    cantidad_plantas: int
    pronosticos: list[PronosticoPlanta]
    advertencia: str = (
        "Prototipo académico: se usan datos simulados. La integración real con "
        "Inventario, Telemetría y Reportes está pendiente de acordar sus contratos."
    )


class RespuestaSalud(BaseModel):
    status: Literal["ok"] = "ok"
    servicio: str = "pronostico-generacion"
