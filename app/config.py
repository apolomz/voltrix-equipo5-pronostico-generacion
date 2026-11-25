"""Configuración del servicio leída desde variables de entorno.

Se evalúa en cada petición para que los tests y los cambios de `.env`
no obliguen a reiniciar el proceso. Los valores por defecto están pensados
para el modo demo del Avance 1.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _int(nombre: str, defecto: int, minimo: int | None = None) -> int:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    try:
        numero = int(valor)
    except ValueError:
        return defecto
    if minimo is not None and numero < minimo:
        return minimo
    return numero


def _float(nombre: str, defecto: float, minimo: float | None = None) -> float:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    try:
        numero = float(valor)
    except ValueError:
        return defecto
    if minimo is not None and numero < minimo:
        return minimo
    return numero


def _url(nombre: str) -> str | None:
    valor = os.getenv(nombre, "").strip()
    return valor.rstrip("/") or None


@dataclass(frozen=True)
class Config:
    """Parámetros operativos del servicio."""

    demo_mode: bool
    demo_plantas: int
    demo_dias: int
    demo_fallback: bool
    inventario_url: str | None
    telemetria_url: str | None
    reportes_url: str | None
    http_timeout: float
    http_retries: int
    fetch_workers: int
    max_workers: int
    parallel_backend: str
    max_concurrent_requests: int
    max_rango_dias: int
    max_paginas: int
    validar_activos: bool
    reportes_generar_si_vacio: bool
    log_level: str

    @classmethod
    def desde_entorno(cls) -> "Config":
        backend = os.getenv("PARALLEL_BACKEND", "thread").strip().lower()
        if backend not in {"thread", "process", "auto"}:
            backend = "thread"
        return cls(
            demo_mode=_bool("DEMO_MODE", True),
            demo_plantas=_int("DEMO_PLANTAS", 80, minimo=1),
            demo_dias=_int("DEMO_DIAS", 30, minimo=2),
            demo_fallback=_bool("DEMO_FALLBACK", False),
            inventario_url=_url("INVENTARIO_URL"),
            telemetria_url=_url("TELEMETRIA_URL"),
            reportes_url=_url("REPORTES_URL"),
            http_timeout=_float("HTTP_TIMEOUT", 5.0, minimo=0.5),
            http_retries=_int("HTTP_RETRIES", 2, minimo=0),
            fetch_workers=_int("FETCH_WORKERS", 8, minimo=1),
            max_workers=_int("MAX_WORKERS", 2, minimo=1),
            parallel_backend=backend,
            max_concurrent_requests=_int("MAX_CONCURRENT_REQUESTS", 1, minimo=1),
            max_rango_dias=_int("MAX_RANGO_DIAS", 31, minimo=1),
            max_paginas=_int("MAX_PAGINAS", 50, minimo=1),
            validar_activos=_bool("VALIDAR_ACTIVOS", True),
            reportes_generar_si_vacio=_bool("REPORTES_GENERAR_SI_VACIO", False),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
