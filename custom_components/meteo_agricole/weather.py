"""Plateforme Météo pour La Météo Agricole avec Double Scraping (Quotidien et Horaire)."""
import logging
import requests
from bs4 import BeautifulSoup
from datetime import timedelta, datetime

from homeassistant.components.weather import (
    WeatherEntity,
    WeatherEntityFeature,
    Forecast,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfSpeed, UnitOfPrecipitationDepth
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
    async_add_entities([MeteoAgricoleWeather(coordinator, lat, lon)], False)


def fetch_all_meteo_data(lat, lon):
    """Effectue le double scraping pour collecter données actuelles, quotidiennes et horaires."""
    base_url = f"https://www.lameteoagricole.net/index.php?lat={lat}&long={lon}&posnf=1"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    session = requests.Session()

    try:
        # --- ÉTAPE 1 : PAGE 10 JOURS (Index) ---
        r1 = session.get(base_url, headers=headers, timeout=15)
        r1.raise_for_status()
        soup1 = BeautifulSoup(r1.text, 'html.parser')
        
        data = {"current": {}, "daily": [], "hourly": []}

        # 1.1 Température actuelle
        temp_now = soup1.find('span', class_='fs-4')
        if temp_now:
            data["current"]["temp"] = float(temp_now.get_text(strip=True).replace('°', ''))
            data["current"]["condition"] = "cloudy" # Par défaut

        # 1.2 Extraction des prévisions quotidiennes (10 Jours)
        daily_row = soup1.find('tr', {'data-rows': 'initial'})
        if daily_row:
            daily_cells = daily_row.find_all('td')
            for index, cell in enumerate(daily_cells):
                try:
                    # Extraction condition
                    img = cell.find('img')
                    cond_text = img['alt'].lower() if img else ""
                    ha_condition = "cloudy"
                    if "soleil" in cond_text or "ensoleillé" in cond_text: ha_condition = "sunny"
                    elif "pluie" in cond_text or "averse" in cond_text: ha_condition = "rainy"
                    elif "partiellement" in cond_text or "peu nuageux" in cond_text: ha_condition = "partlycloudy"

                    # Extraction Max
                    temp_max_span = cell.find('span', class_=lambda c: c and 'fs-4' in c)
                    temp_max = float(temp_max_span.get_text(strip=True).replace('°', '')) if temp_max_span else None

                    # Extraction Min
                    temp_min_span = cell.find('span', string=lambda s: s and 'min' in s)
                    temp_min = None
                    if temp_min_span:
                        temp_min_text = temp_min_span.get_text(strip=True).replace('min', '').replace('°', '').replace('\xa0', '')
                        temp_min = float(temp_min_text)

                    # Le jour 0 est aujourd'hui, jour 1 est demain, etc.
                    forecast_date = datetime.now() + timedelta(days=index)
                    
                    data["daily"].append(
                        Forecast(
                            datetime=forecast_date.isoformat(),
                            condition=ha_condition,
                            native_temperature=temp_max,
                            native_templow=temp_min,
                        )
                    )
                    
                    # On profite du premier jour pour affiner la condition actuelle globale
                    if index == 0:
                        data["current"]["condition"] = ha_condition
                        
                except Exception as e:
                    _LOGGER.debug("Erreur parsing jour %s: %s", index, e)
                    continue

        # --- ÉTAPE 2 : PAGE HORAIRE ---
        link = soup1.find('a', href=lambda h: h and "meteo-heure-par-heure" in h)
        if not link:
            raise UpdateFailed("Lien horaire introuvable sur la page d'index.")
        
        url_hourly = f"https://www.lameteoagricole.net/{link['href']}" if not link['href'].startswith('http') else link['href']
        r2 = session.get(url_hourly, headers=headers, timeout=15)
        r2.raise_for_status()
        soup2 = BeautifulSoup(r2.text, 'html.parser')

        # On cible toutes les cellules <td> du tableau horaire
        hourly_row = soup2.find('tr', {'data-rows': 'initial'})
        cells = hourly_row.find_all('td') if hourly_row else soup2.find_all('td')

        temps_actuel = datetime.now().replace(minute=0, second=0, microsecond=0)
        heure_index = 1
        
        for cell in cells:
            try:
                # 1. Vérifier s'il y a une icône météo (Si non, on ignore la cellule)
                img = cell.find('img')
                if not img or 'alt' not in img.attrs:
                    continue

                # 2. Chercher la température (Un texte contenant "°" mais pas "min")
                temp = None
                spans = cell.find_all('span')
                for span in spans:
                    texte = span.get_text(strip=True)
                    if '°' in texte and len(texte) <= 4 and 'min' not in texte:
                        try:
                            temp = float(texte.replace('°', '').replace('C', '').strip())
                            break
                        except ValueError:
                            continue
                            
                # 3. Si on a trouvé une température, on assemble la prévision
                if temp is not None:
                    cond_text = img['alt'].lower()
                    ha_condition = "cloudy"
                    if "soleil" in cond_text or "dégagé" in cond_text or "ensoleillé" in cond_text: ha_condition = "sunny"
                    elif "pluie" in cond_text or "averse" in cond_text: ha_condition = "rainy"
                    elif "claircie" in cond_text or "partiellement" in cond_text: ha_condition = "partlycloudy"

                    forecast_time = temps_actuel + timedelta(hours=heure_index)
                    data["hourly"].append(
                        Forecast(
                            datetime=forecast_time.isoformat(),
                            condition=ha_condition,
                            native_temperature=temp,
                        )
                    )
                    heure_index += 1 # On passe à l'heure suivante
                    
            except Exception as e:
                _LOGGER.debug("Cellule ignorée : %s", e)
                continue

        return data

    except Exception as e:
        raise UpdateFailed(f"Erreur lors du scraping de la météo : {e}")


class MeteoAgricoleWeather(CoordinatorEntity, WeatherEntity):
    """Représentation de l'entité Météo globale pour Home Assistant."""

    def __init__(self, coordinator, lat, lon):
        super().__init__(coordinator)
        self._attr_name = "La Météo Agricole"
        self._attr_unique_id = f"meteo_agricole_{lat}_{lon}"
        
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
        
        # L'entité annonce fièrement qu'elle supporte le Quotidien ET l'Horaire
        self._attr_supported_features = WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY

    @property
    def condition(self):
        """Condition actuelle (icône principale)."""
        return self.coordinator.data["current"].get("condition")

    @property
    def native_temperature(self):
        """Température actuelle."""
        return self.coordinator.data["current"].get("temp")

    async def async_forecast_daily(self) -> list[Forecast]:
        """Retourne les prévisions sur 10 jours (Min/Max)."""
        return self.coordinator.data.get("daily", [])

    async def async_forecast_hourly(self) -> list[Forecast]:
        """Retourne les prévisions heure par heure."""
        return self.coordinator.data.get("hourly", [])
