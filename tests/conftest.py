from __future__ import annotations

import pytest

from app import forecast, store


@pytest.fixture(autouse=True)
def entorno_demo(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_PLANTAS", "80")
    monkeypatch.setenv("DEMO_DIAS", "30")
    monkeypatch.delenv("INVENTARIO_URL", raising=False)
    monkeypatch.delenv("TELEMETRIA_URL", raising=False)
    monkeypatch.delenv("REPORTES_URL", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    store.limpiar()
    yield
    store.limpiar()
    forecast.cerrar_pools()
