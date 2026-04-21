"""Plateforme Météo pour La Météo Agricole avec Double Scraping et Monitoring."""
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from homeassistant.components.weather import (
    WeatherEntity,
    WeatherEntityFeature,
    Forecast,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_LATITUDE, CONF_LONGITUDE, DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=30)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Configuration de l'entité météo."""
    lat = entry.data.get(CONF_LATITUDE)
    lon = entry.data.get(CONF_LONGITUDE)

    async def async_update_data():
        return await hass.async_add_executor_job(fetch_all_meteo_data, lat, lon)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Météo Agricole",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()
    async_add_entities([MeteoAgricoleWeather(coordinator, entry.title)])

def fetch_all_meteo_data(lat, lon):
    """Récupération des données via scraping (Horaire et Quotidien)."""
    data = {"current": {}, "daily": [], "hourly": []}
    
    # URLs de base (Exemple simplifié, à adapter selon votre logique d'URL)
    url_daily = f"https://www.lameteoagricole.net/meteo-agricole/{lat}-{lon}.html"
    url_hourly = f"https://www.lameteoagricole.net/meteo-heure-par-heure/{lat}-{lon}.html"

    try:
        # 1. SCRAPING PAGE QUOTIDIENNE (Prévisions et Fallback)
        response_d = requests.get(url_daily, timeout=15)
        if response_d.status_code == 200:
            soup_d = BeautifulSoup(response_d.text, "html.parser")
            # Extraction des colonnes du tableau quotidien
            table = soup_d.find("table", class_="table")
            if table:
                rows = table.find_all("td")
                for td in rows:
                    day_forecast = {}
                    
                    # Extraction Température Max/Min
                    temp_span = td.find("span", class_="fw-bold")
                    if temp_span:
                        day_forecast["native_temperature"] = float(temp_span.text.strip())
                    
                    # Extraction Humidité (Moyenne jour)
                    hum_img = td.find("img", alt="humidité")
                    if hum_img:
                        val = hum_img.find_parent("div").find("span", class_="fw-bold")
                        if val: day_forecast["humidity"] = float(val.text.strip())

                    # Extraction Vent (Moyen jour)
                    vent_img = td.find("img", alt="vent")
                    if vent_img:
                        val = vent_img.find_parent("div").find("span", class_="fw-bold")
                        if val: day_forecast["wind_speed"] = float(val.text.strip())

                    # Extraction Rafales (Max jour)
                    raf_img = td.find("img", alt="rafales")
                    if raf_img:
                        val = raf_img.find_parent("div").find("span", class_="fw-bold")
                        if val: day_forecast["wind_gust_speed"] = float(val.text.strip())
                    
                    data["daily"].append(day_forecast)

        # 2. SCRAPING PAGE HORAIRE (Pour la précision de l'instant T)
        response_h = requests.get(url_hourly, timeout=15)
        if response_h.status_code == 200:
            soup_h = BeautifulSoup(response_h.text, "html.parser")
            # Logique similaire pour parser la première colonne (H+0)
            # data["hourly"].append(...)

        # 3. LOGIQUE DE SYNTHÈSE DU "CURRENT"
        if data["hourly"]:
            # Priorité absolue aux données temps réel
            current_source = data["hourly"][0]
            data["current"] = {
                "temp": current_source.get("temperature"),
                "humidity": current_source.get("humidity"),
                "wind_speed": current_source.get("wind_speed"),
                "wind_gust": current_source.get("wind_gust_speed"),
                "condition": current_source.get("condition")
            }
        elif data["daily"]:
            # Fallback sur les moyennes du jour si l'horaire échoue
            current_source = data["daily"][0]
            data["current"] = {
                "temp": current_source.get("native_temperature"),
                "humidity": current_source.get("humidity"),
                "wind_speed": current_source.get("wind_speed"),
                "wind_gust": current_source.get("wind_gust_speed"),
                "condition": current_source.get("condition")
            }

        return data

    except Exception as e:
        _LOGGER.error("Erreur lors du scraping : %s", e)
        raise UpdateFailed(f"Impossible de récupérer les données : {e}")

class MeteoAgricoleWeather(CoordinatorEntity, WeatherEntity):
    """Représentation de l'entité météo dans Home Assistant."""

    def __init__(self, coordinator, name):
        """Initialisation."""
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.name}_{name}"
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_supported_features = (
            WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
        )

    @property
    def native_temperature(self):
        return self.coordinator.data["current"].get("temp")

    @property
    def native_humidity(self):
        return self.coordinator.data["current"].get("humidity")

    @property
    def native_wind_speed(self):
        return self.coordinator.data["current"].get("wind_speed")

    @property
    def native_wind_gust_speed(self):
        return self.coordinator.data["current"].get("wind_gust")

    @property
    def condition(self):
        return self.coordinator.data["current"].get("condition")

    @property
    def extra_state_attributes(self):
        """Attributs additionnels pour le monitoring."""
        attributes = {}
        if self.coordinator.last_update_success:
            attributes["Dernière synchro réussie"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return attributes

    async def async_forecast_daily(self) -> list[Forecast]:
        """Retourne les prévisions quotidiennes."""
        return self.coordinator.data.get("daily", [])

    async def async_forecast_hourly(self) -> list[Forecast]:
        """Retourne les prévisions horaires."""
        return self.coordinator.data.get("hourly", [])
