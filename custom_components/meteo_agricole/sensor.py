"""Plateforme de capteurs pour La Météo Agricole."""
import logging
import requests
from bs4 import BeautifulSoup
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_LATITUDE, CONF_LONGITUDE

_LOGGER = logging.getLogger(__name__)

# On demande à HA de mettre à jour la donnée toutes les 30 minutes
SCAN_INTERVAL = timedelta(minutes=30)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure le capteur Météo Agricole."""
    lat = entry.data.get(CONF_LATITUDE)
    lon = entry.data.get(CONF_LONGITUDE)

    # On ajoute notre capteur à Home Assistant
    async_add_entities([MeteoAgricoleSensor(lat, lon)], True)

class MeteoAgricoleSensor(SensorEntity):
    """Représentation du capteur de La Météo Agricole."""

    def __init__(self, lat, lon):
        """Initialisation du capteur."""
        self._lat = lat
        self._lon = lon
        self._attr_name = "Météo Agricole (Test Scraping)"
        self._attr_unique_id = f"meteo_agricole_{lat}_{lon}"
        self._state = None
        self._attr_native_unit_of_measurement = "°C" # Unité fictive pour l'instant

    @property
    def native_value(self):
        """Retourne l'état du capteur (la valeur extraite)."""
        return self._state

    def update(self) -> None:
        """Action de scraping : va chercher la donnée sur le site web."""
        url = f"https://www.lameteoagricole.net/index.php?lat={self._lat}&long={self._lon}&posnf=1"
        headers = {'User-Agent': 'Mozilla/5.0'}

        try:
            _LOGGER.debug("Téléchargement de %s", url)
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Analyse de la page web avec BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            # === ZONE DE RECHERCHE CSS ===
            # Ici, nous mettons une valeur par défaut en attendant de trouver 
            # la bonne balise (ex: div class="temp-actuelle")
            
            # Exemple bidon : on compte le nombre de balises <div> sur la page 
            # juste pour s'assurer que le HTML a bien été lu.
            div_count = len(soup.find_all('div'))
            self._state = div_count 
            
            # Plus tard, le code ressemblera à :
            # temp_element = soup.find('div', class_='temperature')
            # self._state = float(temp_element.text.replace('°C', ''))

        except Exception as err:
            _LOGGER.error("Erreur lors du scraping de La Météo Agricole: %s", err)
            self._state = None
