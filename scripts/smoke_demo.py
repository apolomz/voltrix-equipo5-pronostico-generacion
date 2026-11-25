"""Smoke test del modo demo para el Avance 1.

Uso:
    python scripts/smoke_demo.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def _imprimir(titulo: str, payload) -> None:
    print(f"\n=== {titulo} ===")
    print(json.dumps(payload, indent=2, ensure_ascii=False)[:2500])


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test del servicio de pronóstico.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--plantas", nargs="+", default=["PL-001", "PL-002", "PL-003"])
    parser.add_argument("--horizonte", type=int, default=6)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    headers = {"X-Equipo-Consumidor": "equipo-5"}
    with httpx.Client(base_url=base, timeout=30, headers=headers) as cliente:
        salud = cliente.get("/health")
        _imprimir("health", salud.json())
        if salud.status_code != 200:
            return 1

        fuentes = cliente.get("/dependencias/estado")
        _imprimir("dependencias", fuentes.json())

        cuerpo = {
            "planta_ids": args.plantas,
            "horizonte_periodos": args.horizonte,
            "frecuencia": "hora",
        }
        for modo, backend in (
            ("secuencial", None),
            ("paralelo", "thread"),
            ("paralelo", "process"),
        ):
            params = {"modo": modo}
            if backend:
                params["backend"] = backend
            respuesta = cliente.post("/pronosticos/generar", params=params, json=cuerpo)
            if respuesta.status_code != 200:
                print(f"ERROR {modo}/{backend}: {respuesta.status_code} {respuesta.text}")
                return 1
            datos = respuesta.json()
            print(
                f"{modo:10s} backend={datos['backend_paralelismo']:9s} "
                f"workers={datos['metricas']['workers']} "
                f"elementos={datos['metricas']['elementos']} "
                f"duracionMs={datos['metricas']['duracionMs']} "
                f"origen={datos['origen_datos']}"
            )

        consulta = cliente.get(f"/pronosticos/{args.plantas[0]}")
        _imprimir(f"GET /pronosticos/{args.plantas[0]}", consulta.json())
        if consulta.status_code != 200:
            return 1

    print("\nSmoke test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
