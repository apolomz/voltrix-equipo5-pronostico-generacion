from __future__ import annotations

from pathlib import Path

import yaml

from app.main import app

RAIZ = Path(__file__).resolve().parents[1]


def _contrato():
    return yaml.safe_load((RAIZ / "openapi.yaml").read_text(encoding="utf-8"))


def test_yaml_es_valido_y_cubre_las_rutas():
    contrato = _contrato()
    assert contrato["openapi"] == "3.0.3"
    rutas_yaml = set(contrato["paths"])
    rutas_app = set(app.openapi()["paths"])
    assert rutas_yaml == rutas_app
    assert "/pronosticos/generar" in rutas_yaml
    assert "/pronosticos/{plantaId}" in rutas_yaml
    assert "/dependencias/estado" in rutas_yaml


def test_esquemas_principales():
    contrato = _contrato()
    esquemas = contrato["components"]["schemas"]
    for nombre in (
        "SolicitudGeneracion",
        "ResultadoGeneracion",
        "PronosticoPlanta",
        "MetricasProcesamiento",
        "Error",
    ):
        assert nombre in esquemas
    assert esquemas["ResultadoGeneracion"]["properties"]["origen_datos"]["enum"] == [
        "demo",
        "dependencias",
        "mixto",
    ]
    assert esquemas["SolicitudGeneracion"]["properties"]["planta_ids"]["minItems"] == 1


def test_ejemplos_usan_identificadores_reales():
    contenido = (RAIZ / "openapi.yaml").read_text(encoding="utf-8")
    assert "PL-001" in contenido
    assert "PLANTA-001" not in contenido
