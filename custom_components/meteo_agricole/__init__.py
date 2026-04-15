"""Initialisation de l'intégration La Météo Agricole."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure La Météo Agricole à partir d'une entrée de configuration."""
    hass.data.setdefault(DOMAIN, {})

    # On demande à HA de charger le fichier sensor.py
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée de configuration (quand on supprime l'intégration)."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    return unload_ok
