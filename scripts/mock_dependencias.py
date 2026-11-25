"""Mock local de los equipos 1, 2 y 4 para probar el modo real.

Uso:
    python scripts/mock_dependencias.py
    # en otra terminal
    DEMO_MODE=false \
      INVENTARIO_URL=http://127.0.0.1:9000/eq1 \
      TELEMETRIA_URL=http://127.0.0.1:9000/eq2 \
      REPORTES_URL=http://127.0.0.1:9000/eq4 \
      uvicorn app.main:app --port 8000

No sustituye los contratos reales: implementa el subconjunto que consume el
Equipo 5 con datos derivados del mismo generador demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sources import demo

app = FastAPI(title="Mock dependencias Voltrix", version="1.0.0")
eq1 = FastAPI(title="Mock Inventario de Activos")
eq2 = FastAPI(title="Mock Telemetría de Plantas")
eq4 = FastAPI(title="Mock Reportes de Generación")


def _error(status: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"codigo": codigo, "mensaje": mensaje, "requestId": "mock"},
    )


def _dt(valor: str | None) -> datetime | None:
    if not valor:
        return None
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


def _iso(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _paginar(items: list[Any], limit: int, offset: int) -> list[Any]:
    return items[offset : offset + limit]


# --------------------------------------------------------------------- Equipo 1
@eq1.get("/health")
def eq1_health():
    return {"estado": "disponible", "baseDatos": "ok", "version": "mock", "tiempoActivoSeg": 0}


@eq1.get("/plantas")
def eq1_plantas(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    plantas = []
    for planta_id in demo.catalogo_plantas(80):
        perfil = demo.perfil_planta(planta_id)
        plantas.append(
            {
                "id": planta_id,
                "nombre": perfil["nombre"],
                "tipo": perfil["tipo"],
                "estado": perfil["estado"],
                "capacidadNominalKw": perfil["capacidad_kw"],
            }
        )
    return {
        "datos": _paginar(plantas, limit, offset),
        "total": len(plantas),
        "limit": limit,
        "offset": offset,
    }


@eq1.get("/plantas/{planta_id}")
def eq1_planta(planta_id: str):
    if planta_id not in demo.catalogo_plantas(80):
        raise _error(404, "NO_ENCONTRADO", f"La planta {planta_id} no existe.")
    perfil = demo.perfil_planta(planta_id)
    return {
        "id": planta_id,
        "nombre": perfil["nombre"],
        "tipo": perfil["tipo"],
        "estado": perfil["estado"],
        "capacidadNominalKw": perfil["capacidad_kw"],
    }


@eq1.get("/activos")
def eq1_activos(
    plantaId: str | None = None,
    estado: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if plantaId and plantaId not in demo.catalogo_plantas(80):
        raise _error(404, "NO_ENCONTRADO", f"La planta {plantaId} no existe.")
    ids = [plantaId] if plantaId else demo.catalogo_plantas(80)
    activos = [activo for planta_id in ids for activo in demo.activos_planta(planta_id)]
    if estado:
        activos = [activo for activo in activos if activo["estado"] == estado]
    return {
        "datos": _paginar(activos, limit, offset),
        "total": len(activos),
        "limit": limit,
        "offset": offset,
    }


@eq1.get("/activos/{activo_id}")
def eq1_activo(activo_id: str):
    for planta_id in demo.catalogo_plantas(80):
        for activo in demo.activos_planta(planta_id):
            if activo["id"] == activo_id:
                return activo
    raise _error(404, "NO_ENCONTRADO", f"El activo {activo_id} no existe.")


# --------------------------------------------------------------------- Equipo 2
@eq2.get("/health")
def eq2_health():
    return {"estado": "disponible", "baseDatos": "ok", "version": "mock", "tiempoActivoSeg": 0}


@eq2.get("/telemetria/{planta_id}")
def eq2_telemetria(
    planta_id: str,
    response: Response,
    desde: str | None = None,
    hasta: str | None = None,
    activoId: str | None = None,
    tipoActivo: str | None = None,
    metrica: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if planta_id not in demo.catalogo_plantas(80):
        raise _error(404, "NO_ENCONTRADO", f"La planta {planta_id} no existe.")
    if metrica and metrica != "potencia":
        return []

    serie = demo.obtener_serie(planta_id, "hora", _dt(desde), _dt(hasta))
    activo = (demo.activos_planta(planta_id) or [{"id": f"{planta_id}-PS-01"}])[0]["id"]
    lecturas = [
        {
            "plantaId": planta_id,
            "activoId": activo,
            "fechaHora": _iso(punto.periodo),
            "metrica": "potencia",
            "valor": punto.generacion_kwh,
            "unidad": "kW",
        }
        for punto in serie.puntos
    ]
    if activoId:
        lecturas = [lectura for lectura in lecturas if lectura["activoId"] == activoId]
    pagina = _paginar(lecturas, limit, offset)
    if offset + len(pagina) < len(lecturas):
        response.headers["X-Next-Offset"] = str(offset + len(pagina))
    return pagina


@eq2.post("/telemetria")
async def eq2_ingesta(request: Request):
    payload = await request.json()
    lecturas = payload.get("lecturas", [])
    return {
        "recibidas": len(lecturas),
        "procesadas": len(lecturas),
        "descartadas": 0,
        "activosInvalidos": [],
        "metricas": {
            "modo": "paralelo",
            "workers": 1,
            "elementos": len(lecturas),
            "duracionMs": 0,
        },
    }


# --------------------------------------------------------------------- Equipo 4
@eq4.get("/health")
def eq4_health():
    return {"estado": "disponible", "baseDatos": "ok", "version": "mock", "tiempoActivoSeg": 0}


@eq4.get("/reportes/generacion")
def eq4_reportes(
    plantaId: str | None = None,
    activoId: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    granularidad: str = "dia",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if granularidad not in {"hora", "dia", "mes"}:
        raise _error(400, "SOLICITUD_INVALIDA", "granularidad debe ser hora, dia o mes.")
    if plantaId and plantaId not in demo.catalogo_plantas(80):
        raise _error(404, "NO_ENCONTRADO", f"La planta {plantaId} no existe.")

    ids = [plantaId] if plantaId else demo.catalogo_plantas(80)
    generado_en = _iso(datetime.now(timezone.utc))
    agregados = []
    for planta_id in ids:
        frecuencia = "hora" if granularidad in {"hora", "mes"} else "dia"
        serie = demo.obtener_serie(planta_id, frecuencia, _dt(desde), _dt(hasta))
        if granularidad == "mes":
            por_mes: dict[str, float] = {}
            for punto in serie.puntos:
                clave = punto.periodo.strftime("%Y-%m")
                por_mes[clave] = por_mes.get(clave, 0.0) + punto.generacion_kwh
            for clave, energia in sorted(por_mes.items()):
                inicio = datetime.fromisoformat(clave + "-01T00:00:00+00:00")
                agregados.append(
                    _agregado(planta_id, inicio, granularidad, energia, generado_en)
                )
        else:
            for punto in serie.puntos:
                agregados.append(
                    _agregado(planta_id, punto.periodo, granularidad, punto.generacion_kwh, generado_en)
                )

    return {
        "datos": _paginar(agregados, limit, offset),
        "total": len(agregados),
        "limit": limit,
        "offset": offset,
    }


@eq4.post("/reportes/generar")
async def eq4_generar(request: Request):
    payload = await request.json()
    plantas = payload.get("plantaIds") or demo.catalogo_plantas(80)
    return {
        "generados": len(plantas) * 30,
        "metricas": {
            "modo": "paralelo",
            "workers": 2,
            "elementos": len(plantas) * 30,
            "duracionMs": 1,
        },
    }


def _agregado(
    planta_id: str,
    inicio: datetime,
    granularidad: str,
    energia: float,
    generado_en: str,
) -> dict:
    if granularidad == "hora":
        fin = inicio.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        lecturas = 1
    elif granularidad == "dia":
        fin = inicio.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        lecturas = 24
    else:
        fin = (inicio.replace(day=1) + timedelta(days=32)).replace(day=1)
        lecturas = 24 * 30
    return {
        "plantaId": planta_id,
        "activoId": None,
        "tipoActivo": None,
        "granularidad": granularidad,
        "periodoInicio": _iso(inicio),
        "periodoFin": _iso(fin),
        "energiaKwh": round(energia, 4),
        "numeroLecturas": lecturas,
        "generadoEn": generado_en,
    }


app.mount("/eq1", eq1)
app.mount("/eq2", eq2)
app.mount("/eq4", eq4)


@app.get("/health")
def health():
    return {"estado": "disponible", "servicios": ["eq1", "eq2", "eq4"]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
