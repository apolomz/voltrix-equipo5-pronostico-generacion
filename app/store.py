"""Almacenamiento de pronósticos en PostgreSQL o memoria."""

import os

from .schemas import PronosticoPlanta

# Almacenamiento temporal para pruebas locales.
_PRONOSTICOS: dict[str, PronosticoPlanta] = {}


def _postgres_configurado() -> bool:
    """Determina si se configuró una conexión a PostgreSQL."""
    return bool(os.getenv("PGHOST") or os.getenv("DATABASE_URL"))


def _conectar():
    """Establece una conexión con PostgreSQL."""
    import psycopg

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return psycopg.connect(
            database_url,
            connect_timeout=3
        )

    return psycopg.connect(
        host=os.getenv("PGHOST", "db"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "voltrix"),
        user=os.getenv("PGUSER", "voltrix"),
        password=os.getenv("PGPASSWORD"),
        connect_timeout=3
    )


def inicializar() -> None:
    """Crea la tabla de pronósticos si no existe."""

    if not _postgres_configurado():
        return

    with _conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS pronosticos (
                planta_id TEXT PRIMARY KEY,
                contenido JSONB NOT NULL,
                actualizado_en TIMESTAMPTZ DEFAULT NOW()
            )
        """)


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

    if not _postgres_configurado():
        _PRONOSTICOS[pronostico.planta_id] = pronostico
        return

    from psycopg.types.json import Jsonb

    contenido = pronostico.model_dump(mode="json")

    with _conectar() as conexion:
        conexion.execute("""
            INSERT INTO pronosticos (
                planta_id,
                contenido,
                actualizado_en
            )
            VALUES (%s, %s, NOW())

            ON CONFLICT (planta_id)
            DO UPDATE SET
                contenido = EXCLUDED.contenido,
                actualizado_en = NOW()
        """, (
            pronostico.planta_id,
            Jsonb(contenido)
        ))


def obtener(planta_id: str) -> PronosticoPlanta | None:
    """Consulta el último pronóstico de una planta."""

    if not _postgres_configurado():
        return _PRONOSTICOS.get(planta_id)

    with _conectar() as conexion:
        fila = conexion.execute("""
            SELECT contenido
            FROM pronosticos
            WHERE planta_id = %s
        """, (planta_id,)).fetchone()

    if fila is None:
        return None

    return PronosticoPlanta.model_validate(fila[0])


def limpiar() -> None:
    """Limpia los pronósticos almacenados."""

    if not _postgres_configurado():
        _PRONOSTICOS.clear()
        return

    with _conectar() as conexion:
        conexion.execute("DELETE FROM pronosticos")
