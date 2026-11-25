"""Caso de uso: obtener histórico, ejecutar el motor y persistir pronósticos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time

import httpx

from ..config import Config
from ..forecast import calcular_distribuido
from ..schemas import (
    Frecuencia,
    MetricasProcesamiento,
    ModoEjecucion,
    OrigenDatos,
    PuntoPronostico,
    PronosticoPlanta,
    RespuestaGeneracion,
    SolicitudGeneracion,
)
from ..sources import DataInputService
from .. import store

logger = logging.getLogger("voltrix.equipo5.pronostico")


def generar_pronosticos(
    solicitud: SolicitudGeneracion,
    *,
    modo: ModoEjecucion,
    workers: int | None,
    backend: str | None,
    request_id: str | None,
    config: Config,
    http_client: httpx.Client | None,
) -> RespuestaGeneracion:
    servicio = DataInputService(config, http_client=http_client)
    try:
        inicio_datos = time.perf_counter()
        resultado = servicio.obtener_series(
            solicitud.planta_ids,
            solicitud.frecuencia.value,
            solicitud.desde,
            solicitud.hasta,
            request_id=request_id,
        )
        duracion_datos_ms = int((time.perf_counter() - inicio_datos) * 1000)
    finally:
        servicio.cerrar()

    tareas = [
        (
            serie.planta_id,
            [punto.generacion_kwh for punto in serie.puntos],
            solicitud.horizonte_periodos,
        )
        for serie in resultado.series
    ]

    inicio_calculo = time.perf_counter()
    backend_efectivo, workers_usados, calculos = calcular_distribuido(
        tareas,
        modo=modo.value,
        max_workers=workers,
        backend=backend,
    )
    duracion_ms = max(0, round((time.perf_counter() - inicio_calculo) * 1000))

    generado_en = datetime.now(timezone.utc)
    paso = timedelta(hours=1) if solicitud.frecuencia == Frecuencia.HORA else timedelta(days=1)
    series_por_planta = {serie.planta_id: serie for serie in resultado.series}
    pronosticos: list[PronosticoPlanta] = []

    for calculo in calculos:
        serie = series_por_planta[calculo["planta_id"]]
        ultimo_periodo = serie.puntos[-1].periodo
        puntos = [
            PuntoPronostico(
                periodo=ultimo_periodo + paso * (indice + 1),
                generacion_kwh=round(max(0.0, float(valor)), 4),
            )
            for indice, valor in enumerate(calculo["predicciones"])
        ]
        pronosticos.append(
            PronosticoPlanta(
                planta_id=serie.planta_id,
                frecuencia=solicitud.frecuencia,
                generado_en=generado_en,
                valores=puntos,
            )
        )

    store.guardar_muchos(pronosticos)

    modo_efectivo = (
        ModoEjecucion.SECUENCIAL
        if backend_efectivo == "secuencial"
        else ModoEjecucion.PARALELO
    )
    advertencias = list(resultado.advertencias)
    if resultado.origen_datos == "demo":
        advertencias.insert(
            0,
            "Datos simulados por el modo demo; no representan telemetría real.",
        )
    elif resultado.origen_datos == "mixto":
        advertencias.insert(
            0,
            "Parte del histórico es simulado porque algunas dependencias no tenían datos.",
        )
    if len(pronosticos) < len(solicitud.planta_ids):
        advertencias.append(
            f"Se pronosticaron {len(pronosticos)} de {len(solicitud.planta_ids)} plantas solicitadas."
        )

    logger.info(
        "pronostico request_id=%s modo=%s backend=%s workers=%s plantas=%s datos_ms=%s calculo_ms=%s origen=%s",
        request_id,
        modo_efectivo.value,
        backend_efectivo,
        workers_usados,
        len(pronosticos),
        duracion_datos_ms,
        duracion_ms,
        resultado.origen_datos,
    )

    return RespuestaGeneracion(
        modo_ejecucion=modo_efectivo,
        backend_paralelismo=backend_efectivo,
        origen_datos=OrigenDatos(resultado.origen_datos),
        cantidad_plantas=len(pronosticos),
        pronosticos=pronosticos,
        metricas=MetricasProcesamiento(
            modo=modo_efectivo,
            workers=workers_usados,
            elementos=len(pronosticos),
            duracionMs=duracion_ms,
        ),
        advertencia="; ".join(advertencias) if advertencias else None,
    )


__all__ = ["generar_pronosticos"]
