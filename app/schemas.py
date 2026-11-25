"""Esquemas Pydantic del contrato público del Equipo 5."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class Frecuencia(str, Enum):
    HORA = "hora"
    DIA = "dia"


class ModoEjecucion(str, Enum):
    SECUENCIAL = "secuencial"
    PARALELO = "paralelo"


class BackendEjecucion(str, Enum):
    AUTO = "auto"
    THREAD = "thread"
    PROCESS = "process"


class OrigenDatos(str, Enum):
    DEMO = "demo"
    DEPENDENCIAS = "dependencias"
    MIXTO = "mixto"


class SolicitudGeneracion(BaseModel):
    """Solicitud para generar pronósticos de una o varias plantas.

    Se aceptan tanto ``planta_ids`` (contrato actual) como ``plantaIds``
    (convención de la plantilla común) para facilitar la integración.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    planta_ids: list[str] = Field(
        min_length=1,
        validation_alias=AliasChoices("planta_ids", "plantaIds"),
        serialization_alias="planta_ids",
        description="Identificadores de las plantas que se desean pronosticar.",
        examples=[["PL-001", "PL-002"]],
    )
    horizonte_periodos: int = Field(
        default=6,
        ge=1,
        le=168,
        validation_alias=AliasChoices("horizonte_periodos", "horizontePeriodos"),
        serialization_alias="horizonte_periodos",
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

    @field_validator("planta_ids")
    @classmethod
    def _ids_no_vacios(cls, valores: list[str]) -> list[str]:
        limpios = [valor.strip() for valor in valores if valor and valor.strip()]
        if not limpios:
            raise ValueError("debe contener al menos un identificador de planta")
        return limpios

    @field_validator("desde", "hasta")
    @classmethod
    def _zona_horaria(cls, valor: datetime | None) -> datetime | None:
        if valor is not None and (valor.tzinfo is None or valor.utcoffset() is None):
            raise ValueError("debe ser una fecha RFC 3339 con zona horaria")
        return valor

    @model_validator(mode="after")
    def _rango_coherente(self) -> "SolicitudGeneracion":
        if self.desde is not None and self.hasta is not None and self.desde >= self.hasta:
            raise ValueError("'desde' debe ser anterior a 'hasta'")
        return self


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
    origen_datos: OrigenDatos = OrigenDatos.DEMO
    cantidad_plantas: int
    pronosticos: list[PronosticoPlanta]
    metricas: MetricasProcesamiento
    advertencia: str | None = None


class RespuestaSalud(BaseModel):
    estado: Literal["disponible", "no_disponible"] = "disponible"
    baseDatos: Literal["ok", "error"] = "ok"
    version: str = "1.0.0"
    tiempoActivoSeg: int = Field(ge=0)


class EstadoFuente(BaseModel):
    equipo: str
    servicio: str
    url: str | None = None
    estado: Literal["ok", "error", "no_aplica", "no_configurado"]
    latenciaMs: int | None = Field(default=None, ge=0)
    detalle: str | None = None


class RespuestaDependencias(BaseModel):
    modoDatos: Literal["demo", "real"]
    fuentes: list[EstadoFuente]


class DetalleError(BaseModel):
    campo: str
    problema: str


class ErrorResponse(BaseModel):
    codigo: str
    mensaje: str
    requestId: str
    detalles: list[DetalleError] | None = None
