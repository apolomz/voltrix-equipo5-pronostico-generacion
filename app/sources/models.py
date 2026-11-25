"""Modelos de las APIs proveedoras y series normalizadas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ModeloUpstream(BaseModel):
    """Los contratos de otros equipos pueden crecer; ignoramos campos extra."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Planta(ModeloUpstream):
    id: str = Field(validation_alias=AliasChoices("id", "plantaId", "planta_id", "codigo"))
    nombre: str | None = Field(
        default=None,
        validation_alias=AliasChoices("nombre", "name", "descripcion"),
    )
    estado: str = Field(
        default="operativo",
        validation_alias=AliasChoices("estado", "estadoOperativo", "estado_operativo"),
    )
    ubicacion: str | None = None


class Activo(ModeloUpstream):
    id: str = Field(validation_alias=AliasChoices("id", "activoId", "activo_id"))
    planta_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("plantaId", "planta_id"),
    )
    tipo: str | None = Field(
        default=None,
        validation_alias=AliasChoices("tipo", "tipoActivo", "tipo_activo"),
    )
    estado: str = Field(
        default="operativo",
        validation_alias=AliasChoices("estado", "estadoOperativo", "estado_operativo"),
    )
    capacidad_nominal_kw: float | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "capacidadNominalKw", "capacidad_nominal_kw", "capacidadKw", "capacidad_kw"
        ),
    )


class Lectura(ModeloUpstream):
    planta_id: str = Field(validation_alias=AliasChoices("plantaId", "planta_id"))
    activo_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("activoId", "activo_id"),
    )
    fecha_hora: datetime = Field(validation_alias=AliasChoices("fechaHora", "fecha_hora"))
    metrica: str
    valor: float
    unidad: str = ""
    estado_reportado: str | None = Field(
        default=None,
        validation_alias=AliasChoices("estadoReportado", "estado_reportado"),
    )


class Agregado(ModeloUpstream):
    planta_id: str = Field(validation_alias=AliasChoices("plantaId", "planta_id"))
    activo_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("activoId", "activo_id"),
    )
    granularidad: str = "dia"
    periodo_inicio: datetime = Field(
        validation_alias=AliasChoices("periodoInicio", "periodo_inicio")
    )
    periodo_fin: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("periodoFin", "periodo_fin"),
    )
    energia_kwh: float = Field(
        validation_alias=AliasChoices("energiaKwh", "energia_kwh", "generacionKwh", "generacion_kwh")
    )
    numero_lecturas: int | None = Field(
        default=None,
        validation_alias=AliasChoices("numeroLecturas", "numero_lecturas"),
    )


@dataclass(frozen=True)
class PuntoSerie:
    periodo: datetime
    generacion_kwh: float


@dataclass
class SeriePlanta:
    planta_id: str
    puntos: list[PuntoSerie]
    origen: str
    estado_planta: str = "operativo"
    advertencias: list[str] = field(default_factory=list)


@dataclass
class ResultadoSeries:
    series: list[SeriePlanta]
    origen_datos: str
    advertencias: list[str] = field(default_factory=list)


def extraer_lista(payload: Any, claves: tuple[str, ...] = ("datos", "data", "items")) -> list[Any]:
    """Acepta listas directas o páginas con ``datos``/``data``/``items``."""

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for clave in claves:
            valor = payload.get(clave)
            if isinstance(valor, list):
                return valor
    return []


def extraer_total(payload: Any) -> int | None:
    if isinstance(payload, dict):
        for clave in ("total", "totalElementos", "count"):
            valor = payload.get(clave)
            if isinstance(valor, int):
                return valor
    return None
