import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_LATITUDE, CONF_LONGITUDE

class MeteoAgricoleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère le flux de configuration pour La Météo Agricole."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Première étape de configuration lancée par l'utilisateur."""
        errors = {}

        if user_input is not None:
            # Ici, nous pourrions ajouter une validation plus poussée
            # Pour le moment, on crée l'entrée directement
            return self.async_create_entry(
                title=f"Météo Agricole ({user_input[CONF_LATITUDE]}, {user_input[CONF_LONGITUDE]})",
                data=user_input,
            )

        # Définition du formulaire avec les coordonnées par défaut de HA
        # ou des champs vides
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_LATITUDE, 
                    default=self.hass.config.latitude
                ): cv.latitude,
                vol.Required(
                    CONF_LONGITUDE, 
                    default=self.hass.config.longitude
                ): cv.longitude,
            }
        )

        return self.async_show_form(
            step_id="user", 
            data_schema=data_schema, 
            errors=errors
        )
