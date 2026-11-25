"""Compatibilidad con la API anterior de datos demo.

El generador vive ahora en :mod:`app.sources.demo`.
"""

from .sources.demo import obtener_historico_demo

__all__ = ["obtener_historico_demo"]
