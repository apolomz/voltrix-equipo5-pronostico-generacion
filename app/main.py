from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException

from .demo_data import obtener_historico_demo
from .forecast import calcular_distribuido
from .schemas import (
    Frecuencia,
    PronosticoPlanta,
    PuntoPronostico,
    RespuestaGeneracion,
    RespuestaSalud,
    SolicitudGeneracion,
)
from . import store

app = FastAPI(
    title="Voltrix Energy - Pronóstico de Generación",
    description=(
        "API del Equipo 5 para estimar la generación futura por planta. "
        "Esta versión inicial usa datos simulados y regresión lineal con NumPy."
    ),
    version="0.1.0",
    openapi_tags=[
        {"name": "Salud", "description": "Estado operativo del servicio."},
        {"name": "Pronósticos", "description": "Generación y consulta de pronósticos."},
    ],
)


@app.get("/health", response_model=RespuestaSalud, tags=["Salud"])
def health() -> RespuestaSalud:
    return RespuestaSalud()


@app.post(
    "/pronosticos/generar",
    response_model=RespuestaGeneracion,
    status_code=200,
    tags=["Pronósticos"],
    summary="Generar pronósticos para varias plantas",
)
def generar_pronosticos(solicitud: SolicitudGeneracion) -> RespuestaGeneracion:
    frecuencia = solicitud.frecuencia.value
    tareas = []
    historicos_por_planta: dict[str, list[dict]] = {}

    # Prototipo: se simula la respuesta de Telemetría. Luego se reemplazará
    # por clientes HTTP hacia Inventario, Telemetría y Reportes.
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

    backend, resultados = calcular_distribuido(tareas)
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

    modo = "paralelo" if len(tareas) > 1 else "secuencial_por_una_planta"
    return RespuestaGeneracion(
        modo_ejecucion=modo,
        backend_paralelismo=backend,
        cantidad_plantas=len(pronosticos),
        pronosticos=pronosticos,
    )


@app.get(
    "/pronosticos/{plantaId}",
    response_model=PronosticoPlanta,
    tags=["Pronósticos"],
    summary="Consultar el último pronóstico de una planta",
)
def consultar_pronostico(plantaId: str) -> PronosticoPlanta:
    pronostico = store.obtener(plantaId)
    if pronostico is None:
        raise HTTPException(
            status_code=404,
            detail=f"No existe un pronóstico generado para la planta {plantaId}.",
        )
    return pronostico
