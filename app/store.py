"""Almacenamiento de pronósticos en PostgreSQL o memoria."""

from __future__ import annotations

import logging
import os
import threading

from .schemas import PronosticoPlanta
from .sources.errors import ErrorDatos

logger = logging.getLogger("voltrix.equipo5.store")

# Almacenamiento temporal para pruebas locales.
_PRONOSTICOS: dict[str, PronosticoPlanta] = {}
_LOCK = threading.Lock()


def _postgres_configurado() -> bool:
    """Determina si se configuró una conexión a PostgreSQL."""
    return bool(os.getenv("PGHOST") or os.getenv("DATABASE_URL"))


def _conectar():
    """Establece una conexión con PostgreSQL."""
    import psycopg

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return psycopg.connect(database_url, connect_timeout=3)

    return psycopg.connect(
        host=os.getenv("PGHOST", "db"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "voltrix"),
        user=os.getenv("PGUSER", "voltrix"),
        password=os.getenv("PGPASSWORD"),
        connect_timeout=3,
    )


def inicializar() -> None:
    """Crea la tabla de pronósticos si no existe.

    Si la base de datos aún no está disponible, el servicio arranca igual y
    ``/health`` responde 503; así un fallo de PostgreSQL no impide diagnosticar
    la API.
    """

    if not _postgres_configurado():
        return

    try:
        with _conectar() as conexion:
            conexion.execute(
                """
                CREATE TABLE IF NOT EXISTS pronosticos (
                    planta_id TEXT PRIMARY KEY,
                    contenido JSONB NOT NULL,
                    actualizado_en TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
    except Exception as exc:  # pragma: no cover - depende de infraestructura
        logger.error("No se pudo inicializar PostgreSQL: %s", exc)


def esta_disponible() -> bool:
    """Comprueba la conexión con PostgreSQL."""

    if not _postgres_configurado():
        return True

    try:
        with _conectar() as conexion:
            conexion.execute("SELECT 1")
        return True
    except Exception:
        return False


def guardar(pronostico: PronosticoPlanta) -> None:
    """Guarda o actualiza un pronóstico."""

    guardar_muchos([pronostico])


def guardar_muchos(pronosticos: list[PronosticoPlanta]) -> None:
    """Guarda un lote de pronósticos en una sola transacción."""

    if not pronosticos:
        return

    if not _postgres_configurado():
        with _LOCK:
            for pronostico in pronosticos:
                _PRONOSTICOS[pronostico.planta_id] = pronostico
        return

    from psycopg.types.json import Jsonb

    try:
        with _conectar() as conexion:
            for pronostico in pronosticos:
                contenido = pronostico.model_dump(mode="json")
                conexion.execute(
                    """
                    INSERT INTO pronosticos (planta_id, contenido, actualizado_en)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (planta_id)
                    DO UPDATE SET
                        contenido = EXCLUDED.contenido,
                        actualizado_en = NOW()
                    """,
                    (pronostico.planta_id, Jsonb(contenido)),
                )
    except Exception as exc:
        raise ErrorDatos(
            503,
            "NO_DISPONIBLE",
            "No hay conexión con la base de datos de pronósticos.",
            [{"campo": "postgresql", "problema": str(exc)[:300]}],
        ) from exc


def obtener(planta_id: str) -> PronosticoPlanta | None:
    """Consulta el último pronóstico de una planta."""

    if not _postgres_configurado():
        with _LOCK:
            return _PRONOSTICOS.get(planta_id)

    try:
        with _conectar() as conexion:
            fila = conexion.execute(
                """
                SELECT contenido
                FROM pronosticos
                WHERE planta_id = %s
                """,
                (planta_id,),
            ).fetchone()
    except Exception as exc:
        raise ErrorDatos(
            503,
            "NO_DISPONIBLE",
            "No hay conexión con la base de datos de pronósticos.",
            [{"campo": "postgresql", "problema": str(exc)[:300]}],
        ) from exc

    if fila is None:
        return None
    return PronosticoPlanta.model_validate(fila[0])


def limpiar() -> None:
    """Limpia los pronósticos almacenados."""

    if not _postgres_configurado():
        with _LOCK:
            _PRONOSTICOS.clear()
        return

    with _conectar() as conexion:
        conexion.execute("DELETE FROM pronosticos")
