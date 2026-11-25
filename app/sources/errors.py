"""Errores de la capa de datos con equivalencia HTTP."""

from __future__ import annotations

from typing import Any


class ErrorDatos(Exception):
    """Error de negocio o de integración que la API traduce a un Error común."""

    def __init__(
        self,
        status_code: int,
        codigo: str,
        mensaje: str,
        detalles: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []
        self.headers = headers or {}
        super().__init__(mensaje)


class ConfiguracionIncompletaError(ErrorDatos):
    def __init__(self, mensaje: str, detalles: list[dict[str, Any]] | None = None) -> None:
        super().__init__(503, "CONFIGURACION_INCOMPLETA", mensaje, detalles)


class DependenciaError(ErrorDatos):
    """Una API de otro equipo falló o respondió con un estado no esperado."""

    def __init__(
        self,
        equipo: str,
        servicio: str,
        operacion: str,
        mensaje: str,
        status_code: int | None = None,
        detalle: str | None = None,
    ) -> None:
        self.equipo = equipo
        self.servicio = servicio
        self.operacion = operacion
        self.status_code_upstream = status_code
        detalle_final = detalle or mensaje
        if status_code is not None:
            detalle_final = f"{detalle_final} (HTTP {status_code})"
        super().__init__(
            502,
            "DEPENDENCIA_FALLIDA",
            mensaje,
            [{"campo": equipo, "problema": f"{operacion}: {detalle_final}"}],
        )


class PlantaNoEncontradaError(ErrorDatos):
    def __init__(self, plantas: list[str]) -> None:
        detalle = ", ".join(plantas)
        super().__init__(
            404,
            "PLANTA_NO_ENCONTRADA",
            f"No existe en Inventario de Activos: {detalle}.",
            [{"campo": "planta_ids", "problema": f"IDs desconocidos: {detalle}"}],
        )


class DatosNoDisponiblesError(ErrorDatos):
    def __init__(self, mensaje: str, detalles: list[dict[str, Any]] | None = None) -> None:
        super().__init__(502, "DATOS_NO_DISPONIBLES", mensaje, detalles)


class RangoInvalidoError(ErrorDatos):
    def __init__(self, mensaje: str) -> None:
        super().__init__(
            400,
            "RANGO_INVALIDO",
            mensaje,
            [{"campo": "desde/hasta", "problema": mensaje}],
        )
