"""Generación determinista de datos de prueba para desarrollar sin APIs externas."""

from datetime import datetime, timedelta, timezone


def obtener_historico_demo(planta_id: str, frecuencia: str = "hora") -> list[dict]:
    """Devuelve 24 observaciones ficticias; NO representa telemetría real."""
    # Desplazamiento estable para que cada planta tenga una serie ligeramente distinta.
    desplazamiento = sum(ord(caracter) for caracter in planta_id) % 7
    valores_base = [10, 12, 13, 15, 14, 17, 18, 20, 19, 22, 23, 24,
                    23, 26, 27, 29, 28, 31, 32, 34, 33, 35, 37, 38]
    ahora = datetime.now(timezone.utc)
    paso = timedelta(hours=1) if frecuencia == "hora" else timedelta(days=1)
    fin = ahora.replace(minute=0, second=0, microsecond=0) if frecuencia == "hora" else ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = fin - paso * (len(valores_base) - 1)

    return [
        {
            "periodo": inicio + paso * indice,
            "generacion_kwh": float(valor + desplazamiento),
        }
        for indice, valor in enumerate(valores_base)
    ]
