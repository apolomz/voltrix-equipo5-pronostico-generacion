from datetime import datetime, timezone

import pytest

from app.sources import demo
from app.sources.errors import PlantaNoEncontradaError


def test_catalogo_tiene_ochenta_plantas():
    catalogo = demo.catalogo_plantas(80)
    assert len(catalogo) == 80
    assert catalogo[0] == "PL-001"
    assert catalogo[-1] == "PL-080"


def test_serie_es_determinista():
    desde = datetime(2026, 11, 1, tzinfo=timezone.utc)
    hasta = datetime(2026, 11, 2, tzinfo=timezone.utc)
    primera = demo.obtener_serie("PL-001", "hora", desde, hasta)
    segunda = demo.obtener_serie("PL-001", "hora", desde, hasta)
    assert [p.generacion_kwh for p in primera.puntos] == [
        p.generacion_kwh for p in segunda.puntos
    ]
    assert len(primera.puntos) == 24


def test_serie_diaria_y_perfil():
    desde = datetime(2026, 11, 1, tzinfo=timezone.utc)
    hasta = datetime(2026, 11, 5, tzinfo=timezone.utc)
    serie = demo.obtener_serie("PL-001", "dia", desde, hasta)
    assert len(serie.puntos) == 4
    assert all(punto.generacion_kwh >= 0 for punto in serie.puntos)
    assert demo.perfil_planta("PL-001")["tipo"] == "panel_solar"
    assert demo.perfil_planta("PL-070")["tipo"] == "turbina_eolica"
    assert demo.perfil_planta("PL-080")["tipo"] == "hibrida"


def test_planta_desconocida():
    with pytest.raises(PlantaNoEncontradaError):
        demo.obtener_serie("PL-999", "hora")
