"""Almacenamiento temporal en memoria para el prototipo inicial."""

from .schemas import PronosticoPlanta

_PRONOSTICOS: dict[str, PronosticoPlanta] = {}


def guardar(pronostico: PronosticoPlanta) -> None:
    _PRONOSTICOS[pronostico.planta_id] = pronostico


def obtener(planta_id: str) -> PronosticoPlanta | None:
    return _PRONOSTICOS.get(planta_id)


def limpiar() -> None:
    _PRONOSTICOS.clear()
