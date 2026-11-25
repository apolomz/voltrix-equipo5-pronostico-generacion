"""Orquestación de la capa de entrada de datos.

Precedencia en modo real:
1. Inventario de Activos valida las plantas (y opcionalmente sus activos).
2. Reportes de Generación entrega los agregados históricos.
3. Telemetría de Plantas se usa si Reportes no tiene datos.
4. El demo solo se usa si ``DEMO_FALLBACK=true``.

En modo demo no se llama a ningún servicio externo.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import logging
from statistics import fmean

import httpx

from ..config import Config
from . import demo
from .errors import (
    ConfiguracionIncompletaError,
    DatosNoDisponiblesError,
    DependenciaError,
    PlantaNoEncontradaError,
    RangoInvalidoError,
)
from .http import ClienteHttp
from .inventario import InventarioClient
from .models import Activo, Planta, PuntoSerie, ResultadoSeries, SeriePlanta
from .reportes import ReportesClient
from .telemetria import TelemetriaClient

logger = logging.getLogger("voltrix.equipo5.datos")



class DataInputService:
    def __init__(self, config: Config, http_client: httpx.Client | None = None) -> None:
        self.config = config
        self._http_propio: httpx.Client | None = None
        if config.demo_mode:
            self._inventario = None
            self._reportes = None
            self._telemetria = None
            return

        cliente = http_client
        if cliente is None:
            cliente = httpx.Client(
                timeout=config.http_timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
            self._http_propio = cliente

        self._inventario = InventarioClient(
            ClienteHttp(
                config.inventario_url or "",
                "equipo-1",
                "Inventario de Activos",
                timeout=config.http_timeout,
                retries=config.http_retries,
                client=cliente,
            )
        )
        self._reportes = ReportesClient(
            ClienteHttp(
                config.reportes_url or "",
                "equipo-4",
                "Reportes de Generación",
                timeout=config.http_timeout,
                retries=config.http_retries,
                client=cliente,
            )
        )
        self._telemetria = TelemetriaClient(
            ClienteHttp(
                config.telemetria_url or "",
                "equipo-2",
                "Telemetría de Plantas",
                timeout=config.http_timeout,
                retries=config.http_retries,
                client=cliente,
            ),
            max_paginas=config.max_paginas,
        )

    # ------------------------------------------------------------------ público
    def obtener_series(
        self,
        planta_ids: list[str],
        frecuencia: str,
        desde: datetime | None,
        hasta: datetime | None,
        request_id: str | None = None,
    ) -> ResultadoSeries:
        ids = _normalizar_ids(planta_ids)
        if not ids:
            raise PlantaNoEncontradaError(["(lista vacía)"])
        desde_utc, hasta_utc = self._normalizar_rango(desde, hasta)

        if self.config.demo_mode:
            return self._series_demo(ids, frecuencia, desde_utc, hasta_utc)

        self._validar_configuracion()
        plantas = self._cargar_plantas(ids, request_id)
        advertencias: list[str] = []

        for planta_id, planta in plantas.items():
            if planta.estado.lower() not in {"operativo", "activo", "ok", "disponible"}:
                advertencias.append(
                    f"{planta_id} está en estado '{planta.estado}'; el pronóstico puede ser poco confiable."
                )

        if self.config.validar_activos:
            advertencias.extend(self._validar_activos(ids, request_id))

        historicos = self._obtener_historicos(ids, frecuencia, desde_utc, hasta_utc, request_id)
        origenes: dict[str, str] = {
            planta_id: "dependencias"
            for planta_id, puntos in historicos.items()
            if puntos
        }
        faltantes = [planta_id for planta_id in ids if not historicos.get(planta_id)]

        if faltantes and self.config.reportes_generar_si_vacio:
            try:
                self._reportes.generar(
                    faltantes,
                    desde_utc,
                    hasta_utc,
                    _granularidad(frecuencia),
                    request_id=request_id,
                )
                nuevos = self._obtener_historicos(
                    faltantes, frecuencia, desde_utc, hasta_utc, request_id
                )
                for planta_id, puntos in nuevos.items():
                    if puntos:
                        historicos[planta_id] = puntos
                        origenes[planta_id] = "dependencias"
                faltantes = [planta_id for planta_id in ids if not historicos.get(planta_id)]
                advertencias.append(
                    "Reportes no tenía agregados; se solicitó POST /reportes/generar."
                )
            except DependenciaError as exc:
                advertencias.append(f"No se pudo generar el histórico en Reportes: {exc.mensaje}")

        if faltantes:
            por_telemetria = self._obtener_por_telemetria(
                faltantes, frecuencia, desde_utc, hasta_utc, request_id
            )
            for planta_id, puntos in por_telemetria.items():
                if puntos:
                    historicos[planta_id] = puntos
                    origenes[planta_id] = "dependencias"
            usadas = sum(1 for puntos in por_telemetria.values() if puntos)
            if usadas:
                advertencias.append(
                    f"{usadas} planta(s) se completaron con Telemetría porque Reportes no tenía agregados."
                )
            faltantes = [planta_id for planta_id in ids if not historicos.get(planta_id)]

        if faltantes and self.config.demo_fallback:
            for planta_id in faltantes:
                try:
                    serie = demo.obtener_serie(
                        planta_id,
                        frecuencia,
                        desde_utc,
                        hasta_utc,
                        plantas=self.config.demo_plantas,
                        dias=self.config.demo_dias,
                    )
                    historicos[planta_id] = serie.puntos
                    origenes[planta_id] = "demo"
                except Exception:
                    continue
            advertencias.append(
                f"{len(faltantes)} planta(s) sin datos reales usaron el generador demo (DEMO_FALLBACK)."
            )
            faltantes = [planta_id for planta_id in ids if not historicos.get(planta_id)]

        if not any(historicos.values()):
            raise DatosNoDisponiblesError(
                "Ninguna planta tiene histórico disponible en Reportes ni en Telemetría.",
                [{"campo": "planta_ids", "problema": ", ".join(ids)}],
            )

        series: list[SeriePlanta] = []
        usados: set[str] = set()
        for planta_id in ids:
            puntos = historicos.get(planta_id) or []
            if not puntos:
                advertencias.append(f"{planta_id} no tiene datos suficientes y se omitió.")
                continue
            origen = origenes.get(planta_id, "dependencias")
            usados.add(origen)
            series.append(
                SeriePlanta(
                    planta_id=planta_id,
                    puntos=puntos,
                    origen=origen,
                    estado_planta=plantas[planta_id].estado,
                )
            )

        return ResultadoSeries(
            series=series,
            origen_datos=_combinar_origenes(usados),
            advertencias=_deduplicar(advertencias),
        )

    def estado_dependencias(self, request_id: str | None = None) -> list[dict]:
        fuentes = [
            ("equipo-1", "Inventario de Activos", self.config.inventario_url, self._inventario),
            ("equipo-4", "Reportes de Generación", self.config.reportes_url, self._reportes),
            ("equipo-2", "Telemetría de Plantas", self.config.telemetria_url, self._telemetria),
        ]
        if self.config.demo_mode:
            return [
                {
                    "equipo": equipo,
                    "servicio": servicio,
                    "url": url,
                    "estado": "no_aplica",
                    "latenciaMs": None,
                    "detalle": "DEMO_MODE=true: no se consultan dependencias.",
                }
                for equipo, servicio, url, _ in fuentes
            ]

        resultado = []
        for equipo, servicio, url, cliente in fuentes:
            if not url or cliente is None:
                resultado.append(
                    {
                        "equipo": equipo,
                        "servicio": servicio,
                        "url": url,
                        "estado": "no_configurado",
                        "latenciaMs": None,
                        "detalle": "Falta la variable de entorno con la URL base.",
                    }
                )
                continue
            inicio = datetime.now(timezone.utc)
            try:
                cliente.http.get_health(request_id=request_id)
                latencia = int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000)
                resultado.append(
                    {
                        "equipo": equipo,
                        "servicio": servicio,
                        "url": url,
                        "estado": "ok",
                        "latenciaMs": latencia,
                        "detalle": None,
                    }
                )
            except DependenciaError as exc:
                latencia = int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000)
                resultado.append(
                    {
                        "equipo": equipo,
                        "servicio": servicio,
                        "url": url,
                        "estado": "error",
                        "latenciaMs": latencia,
                        "detalle": exc.mensaje,
                    }
                )
        return resultado

    def cerrar(self) -> None:
        if self._http_propio is not None:
            self._http_propio.close()
            self._http_propio = None

    # ------------------------------------------------------------------ demo
    def _series_demo(
        self,
        ids: list[str],
        frecuencia: str,
        desde: datetime,
        hasta: datetime,
    ) -> ResultadoSeries:
        catalogo = set(demo.catalogo_plantas(self.config.demo_plantas))
        desconocidas = [planta_id for planta_id in ids if planta_id not in catalogo]
        if desconocidas:
            raise PlantaNoEncontradaError(desconocidas)

        series = [
            demo.obtener_serie(
                planta_id,
                frecuencia,
                desde,
                hasta,
                plantas=self.config.demo_plantas,
                dias=self.config.demo_dias,
            )
            for planta_id in ids
        ]
        return ResultadoSeries(series=series, origen_datos="demo")

    # ------------------------------------------------------------- inventario
    def _validar_configuracion(self) -> None:
        faltantes = [
            nombre
            for nombre, valor in (
                ("INVENTARIO_URL", self.config.inventario_url),
                ("TELEMETRIA_URL", self.config.telemetria_url),
                ("REPORTES_URL", self.config.reportes_url),
            )
            if not valor
        ]
        if faltantes:
            raise ConfiguracionIncompletaError(
                "DEMO_MODE=false requiere las URLs de las dependencias.",
                [{"campo": nombre, "problema": "Variable de entorno no configurada."} for nombre in faltantes],
            )

    def _cargar_plantas(self, ids: list[str], request_id: str | None) -> dict[str, Planta]:
        assert self._inventario is not None
        error_listado: DependenciaError | None = None
        try:
            plantas = self._inventario.listar_plantas(request_id=request_id)
        except DependenciaError as exc:
            plantas = []
            error_listado = exc

        mapa = {planta.id: planta for planta in plantas}
        faltantes = [planta_id for planta_id in ids if planta_id not in mapa]
        error_individual: DependenciaError | None = None
        if faltantes:
            for planta_id in faltantes:
                try:
                    planta = self._inventario.obtener_planta(planta_id, request_id=request_id)
                except DependenciaError as exc:
                    if exc.status_code_upstream == 404:
                        planta = None
                    else:
                        planta = None
                        error_individual = exc
                if planta is not None:
                    mapa[planta.id] = planta

        desconocidas = [planta_id for planta_id in ids if planta_id not in mapa]
        if desconocidas:
            # Si Inventario no respondió, el problema es de la dependencia (502),
            # no de los identificadores (404).
            if error_listado is not None and len(mapa) == 0:
                raise error_listado
            if error_individual is not None:
                raise error_individual
            raise PlantaNoEncontradaError(desconocidas)
        return {planta_id: mapa[planta_id] for planta_id in ids}

    def _validar_activos(self, ids: list[str], request_id: str | None) -> list[str]:
        assert self._inventario is not None
        advertencias: list[str] = []
        activos: dict[str, list[Activo]] = {}

        def cargar(planta_id: str) -> list[Activo]:
            try:
                return self._inventario.listar_activos(planta_id, request_id=request_id)
            except DependenciaError as exc:
                if exc.status_code_upstream == 404:
                    return []
                raise

        with ThreadPoolExecutor(max_workers=min(self.config.fetch_workers, len(ids))) as pool:
            futuros = {pool.submit(cargar, planta_id): planta_id for planta_id in ids}
            for futuro in as_completed(futuros):
                planta_id = futuros[futuro]
                activos[planta_id] = futuro.result()

        for planta_id in ids:
            lista = activos.get(planta_id, [])
            if not lista:
                advertencias.append(f"{planta_id} no reporta activos en Inventario.")
                continue
            if all(
                activo.estado.lower() in {"fuera_de_servicio", "falla", "inactivo"}
                for activo in lista
            ):
                advertencias.append(
                    f"{planta_id} tiene todos sus activos fuera de servicio; el pronóstico puede ser cero."
                )
        return advertencias

    # --------------------------------------------------------------- históricos
    def _obtener_historicos(
        self,
        ids: list[str],
        frecuencia: str,
        desde: datetime,
        hasta: datetime,
        request_id: str | None,
    ) -> dict[str, list[PuntoSerie]]:
        assert self._reportes is not None
        granularidad = _granularidad(frecuencia)
        resultado: dict[str, list[PuntoSerie]] = {}

        def cargar(planta_id: str) -> list[PuntoSerie]:
            try:
                agregados = self._reportes.historial(
                    planta_id, desde, hasta, granularidad, request_id=request_id
                )
            except DependenciaError as exc:
                if exc.status_code_upstream == 404:
                    return []
                raise
            return _puntos_desde_agregados(agregados, desde, hasta)

        with ThreadPoolExecutor(max_workers=min(self.config.fetch_workers, len(ids))) as pool:
            futuros = {pool.submit(cargar, planta_id): planta_id for planta_id in ids}
            for futuro in as_completed(futuros):
                planta_id = futuros[futuro]
                try:
                    resultado[planta_id] = futuro.result()
                except DependenciaError as exc:
                    logger.warning("Reportes falló para %s: %s", planta_id, exc.mensaje)
                    resultado[planta_id] = []
        return resultado

    def _obtener_por_telemetria(
        self,
        ids: list[str],
        frecuencia: str,
        desde: datetime,
        hasta: datetime,
        request_id: str | None,
    ) -> dict[str, list[PuntoSerie]]:
        assert self._telemetria is not None
        resultado: dict[str, list[PuntoSerie]] = {}

        def cargar(planta_id: str) -> list[PuntoSerie]:
            lecturas = self._telemetria.lecturas(
                planta_id, desde, hasta, request_id=request_id
            )
            return _puntos_desde_telemetria(lecturas, frecuencia, desde, hasta)

        with ThreadPoolExecutor(max_workers=min(self.config.fetch_workers, len(ids))) as pool:
            futuros = {pool.submit(cargar, planta_id): planta_id for planta_id in ids}
            for futuro in as_completed(futuros):
                planta_id = futuros[futuro]
                try:
                    resultado[planta_id] = futuro.result()
                except DependenciaError as exc:
                    logger.warning("Telemetría falló para %s: %s", planta_id, exc.mensaje)
                    resultado[planta_id] = []
        return resultado

    # ------------------------------------------------------------------ rango
    def _normalizar_rango(
        self, desde: datetime | None, hasta: datetime | None
    ) -> tuple[datetime, datetime]:
        ahora = datetime.now(timezone.utc)
        fin = _a_utc(hasta) if hasta is not None else ahora
        inicio = _a_utc(desde) if desde is not None else fin - timedelta(days=self.config.demo_dias)
        if inicio >= fin:
            raise RangoInvalidoError("'desde' debe ser anterior a 'hasta'.")
        if (fin - inicio).days > self.config.max_rango_dias:
            raise RangoInvalidoError(
                f"El rango máximo es de {self.config.max_rango_dias} días."
            )
        return inicio, fin


# --------------------------------------------------------------------- helpers
def _normalizar_ids(ids: list[str]) -> list[str]:
    vistos: list[str] = []
    for planta_id in ids:
        limpio = planta_id.strip()
        if limpio and limpio not in vistos:
            vistos.append(limpio)
    return vistos


def _a_utc(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def _granularidad(frecuencia: str) -> str:
    return "hora" if frecuencia == "hora" else "dia"


def _puntos_desde_agregados(agregados, desde: datetime, hasta: datetime) -> list[PuntoSerie]:
    propios = [agregado for agregado in agregados if agregado.activo_id is None]
    if propios:
        agregados = propios
    por_periodo: dict[datetime, float] = {}
    for agregado in agregados:
        periodo = _a_utc(agregado.periodo_inicio)
        if periodo < desde or periodo >= hasta:
            continue
        valor = max(0.0, float(agregado.energia_kwh))
        por_periodo[periodo] = valor
    return [
        PuntoSerie(periodo=periodo, generacion_kwh=valor)
        for periodo, valor in sorted(por_periodo.items())
    ]


def _puntos_desde_telemetria(
    lecturas, frecuencia: str, desde: datetime, hasta: datetime
) -> list[PuntoSerie]:
    directas: dict[datetime, float] = {}
    potencias: dict[datetime, list[float]] = {}

    for lectura in lecturas:
        periodo = _a_utc(lectura.fecha_hora)
        if frecuencia == "dia":
            periodo = periodo.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            periodo = periodo.replace(minute=0, second=0, microsecond=0)
        if periodo < desde or periodo >= hasta:
            continue

        metrica = lectura.metrica.lower()
        unidad = lectura.unidad.lower().replace(" ", "")
        if "energia" in metrica or unidad in {"kwh", "kw-h", "kilowatt-hour"}:
            directas[periodo] = directas.get(periodo, 0.0) + max(0.0, float(lectura.valor))
            continue

        if "potencia" in metrica or unidad in {"w", "kw"}:
            valor_kw = float(lectura.valor)
            if unidad == "w" or (unidad == "" and valor_kw > 500):
                valor_kw /= 1000.0
            potencias.setdefault(periodo, []).append(max(0.0, valor_kw))
            continue

        if "generacion" in metrica:
            valor = max(0.0, float(lectura.valor))
            if "kwh" in unidad:
                directas[periodo] = directas.get(periodo, 0.0) + valor
            else:
                potencias.setdefault(periodo, []).append(valor)

    horas = 24.0 if frecuencia == "dia" else 1.0
    puntos: list[PuntoSerie] = []
    for periodo in sorted(set(directas) | set(potencias)):
        if periodo in directas:
            energia = directas[periodo]
        else:
            energia = fmean(potencias[periodo]) * horas
        puntos.append(PuntoSerie(periodo=periodo, generacion_kwh=round(max(0.0, energia), 4)))
    return [punto for punto in puntos if desde <= punto.periodo < hasta]


def _combinar_origenes(origenes: set[str]) -> str:
    if not origenes:
        return "demo"
    if origenes == {"demo"}:
        return "demo"
    if "demo" in origenes:
        return "mixto"
    return "dependencias"


def _deduplicar(valores: list[str]) -> list[str]:
    vistos: list[str] = []
    for valor in valores:
        if valor and valor not in vistos:
            vistos.append(valor)
    return vistos
