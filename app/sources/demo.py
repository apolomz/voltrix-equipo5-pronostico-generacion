"""Generador determinista de datos para el modo demo.

No pretende ser un modelo físico: busca series con forma solar/eólica,
suficiente variación y resultados reproducibles para la demostración y los
benchmarks. Cada planta tiene un perfil estable derivado de su identificador.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import math

from .errors import PlantaNoEncontradaError, RangoInvalidoError
from .models import PuntoSerie, SeriePlanta

_EPOCA = date(2026, 1, 1)


def catalogo_plantas(total: int = 80) -> list[str]:
    return [f"PL-{indice:03d}" for indice in range(1, max(1, total) + 1)]


def _semilla(planta_id: str) -> int:
    return int(hashlib.sha256(planta_id.encode("utf-8")).hexdigest()[:10], 16)


def perfil_planta(planta_id: str) -> dict:
    """Tipo, capacidad y activos coherentes con las convenciones del Equipo 1."""

    semilla = _semilla(planta_id)
    indice = int(planta_id.split("-")[-1]) if planta_id.split("-")[-1].isdigit() else semilla % 80
    if indice <= 60:
        tipo = "panel_solar"
        capacidad = 80.0 + (semilla % 120)
        activos = [
            {"tipo": "panel_solar", "sufijo": "PS", "cantidad": 3, "capacidad": capacidad / 3},
            {"tipo": "banco_baterias", "sufijo": "BB", "cantidad": 1, "capacidad": capacidad / 4},
        ]
    elif indice <= 75:
        tipo = "turbina_eolica"
        capacidad = 60.0 + (semilla % 100)
        activos = [
            {"tipo": "turbina_eolica", "sufijo": "TB", "cantidad": 2, "capacidad": capacidad / 2},
            {"tipo": "banco_baterias", "sufijo": "BB", "cantidad": 1, "capacidad": capacidad / 4},
        ]
    else:
        tipo = "hibrida"
        capacidad = 100.0 + (semilla % 150)
        activos = [
            {"tipo": "panel_solar", "sufijo": "PS", "cantidad": 2, "capacidad": capacidad / 2},
            {"tipo": "turbina_eolica", "sufijo": "TB", "cantidad": 1, "capacidad": capacidad / 3},
            {"tipo": "banco_baterias", "sufijo": "BB", "cantidad": 1, "capacidad": capacidad / 4},
        ]
    return {
        "planta_id": planta_id,
        "nombre": f"Microplanta {planta_id}",
        "tipo": tipo,
        "capacidad_kw": round(capacidad, 2),
        "activos": activos,
        "estado": "operativo",
    }


def activos_planta(planta_id: str) -> list[dict]:
    perfil = perfil_planta(planta_id)
    activos: list[dict] = []
    for grupo in perfil["activos"]:
        for numero in range(1, grupo["cantidad"] + 1):
            activos.append(
                {
                    "id": f"{planta_id}-{grupo['sufijo']}-{numero:02d}",
                    "plantaId": planta_id,
                    "tipo": grupo["tipo"],
                    "estado": "operativo",
                    "capacidadNominalKw": round(grupo["capacidad"], 2),
                }
            )
    return activos


def _factor_solar(hora: float, dia: int, semilla: int) -> float:
    if hora < 6.0 or hora > 18.0:
        return 0.0
    sol = math.sin(math.pi * (hora - 6.0) / 12.0)
    nubosidad = 0.86 + 0.14 * math.sin(dia * 0.7 + (semilla % 19))
    return max(0.0, sol * nubosidad)


def _factor_viento(hora: float, dia: int, semilla: int) -> float:
    base = 0.42 + 0.22 * math.sin(dia * 0.9 + (semilla % 23))
    rafaga = 0.16 * math.sin(hora * 0.55 + (semilla % 31))
    return min(1.0, max(0.0, base + rafaga))


def _energia_hora(perfil: dict, periodo: datetime, semilla: int) -> float:
    hora = periodo.hour + periodo.minute / 60.0
    dia = (periodo.date() - _EPOCA).days
    tipo = perfil["tipo"]
    if tipo == "panel_solar":
        factor = _factor_solar(hora, dia, semilla)
    elif tipo == "turbina_eolica":
        factor = _factor_viento(hora, dia, semilla)
    else:
        factor = 0.65 * _factor_solar(hora, dia, semilla) + 0.45 * _factor_viento(
            hora, dia, semilla
        )
    # Pequeña variación determinista para que la regresión no sea perfecta.
    ruido = 0.97 + 0.03 * math.sin(dia * 1.7 + periodo.hour * 0.37 + (semilla % 13))
    return max(0.0, perfil["capacidad_kw"] * factor * ruido)


def _truncar(momento: datetime, frecuencia: str) -> datetime:
    if frecuencia == "hora":
        return momento.replace(minute=0, second=0, microsecond=0)
    return momento.replace(hour=0, minute=0, second=0, microsecond=0)


def _a_utc(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def obtener_serie(
    planta_id: str,
    frecuencia: str,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    *,
    plantas: int = 80,
    dias: int = 30,
) -> SeriePlanta:
    """Serie histórica simulada, estable para la misma planta y rango."""

    if frecuencia not in {"hora", "dia"}:
        raise RangoInvalidoError("La frecuencia debe ser 'hora' o 'dia'.")
    if planta_id not in catalogo_plantas(plantas):
        raise PlantaNoEncontradaError([planta_id])

    ahora = datetime.now(timezone.utc)
    fin = _truncar(_a_utc(hasta) if hasta is not None else ahora, frecuencia)
    if desde is None:
        inicio = fin - timedelta(days=max(2, dias) - 1)
        inicio = _truncar(inicio, frecuencia)
    else:
        inicio = _truncar(_a_utc(desde), frecuencia)
    if inicio >= fin:
        raise RangoInvalidoError("El rango debe contener al menos dos periodos históricos.")

    perfil = perfil_planta(planta_id)
    semilla = _semilla(planta_id)
    paso = timedelta(hours=1) if frecuencia == "hora" else timedelta(days=1)
    puntos: list[PuntoSerie] = []
    periodo = inicio
    while periodo < fin:
        if frecuencia == "hora":
            energia = _energia_hora(perfil, periodo, semilla)
        else:
            energia = sum(
                _energia_hora(perfil, periodo + timedelta(hours=hora), semilla)
                for hora in range(24)
            )
        puntos.append(PuntoSerie(periodo=periodo, generacion_kwh=round(energia, 4)))
        periodo += paso

    if len(puntos) < 2:
        raise RangoInvalidoError("El rango debe contener al menos dos periodos históricos.")
    return SeriePlanta(planta_id=planta_id, puntos=puntos, origen="demo")


def obtener_historico_demo(planta_id: str, frecuencia: str = "hora") -> list[dict]:
    """Compatibilidad con la API anterior: lista de diccionarios."""

    serie = obtener_serie(planta_id, frecuencia)
    return [
        {"periodo": punto.periodo, "generacion_kwh": punto.generacion_kwh}
        for punto in serie.puntos
    ]
