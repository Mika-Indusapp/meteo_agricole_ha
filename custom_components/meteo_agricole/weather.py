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
    title = entry.title

    async def async_update_data():
        return await hass.async_add_executor_job(fetch_all_meteo_data, lat, lon)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"Météo Agricole {title}",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()
    async_add_entities([MeteoAgricoleWeather(coordinator, title, lat, lon)], False)


def fetch_all_meteo_data(lat, lon):
    """Effectue le double scraping pour collecter données actuelles, quotidiennes et horaires."""
    base_url = f"https://www.lameteoagricole.net/index.php?lat={lat}&long={lon}&posnf=1"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    session = requests.Session()

    data = {"current": {}, "daily": [], "hourly": []}

    try:
        # --- ÉTAPE 1 : PAGE 10 JOURS (Index) ---
        r1 = session.get(base_url, headers=headers, timeout=15)
        r1.raise_for_status()
        soup1 = BeautifulSoup(r1.text, 'html.parser')
        
        # 1.1 Température initiale
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
                    cond_text = img['alt'].lower() if img and 'alt' in img.attrs else ""
                    ha_condition = get_ha_condition(cond_text)

                    # Extraction Max
                    temp_max_span = cell.find('span', class_=lambda c: c and 'fs-4' in c)
                    temp_max = float(temp_max_span.get_text(strip=True).replace('°', '')) if temp_max_span else None

                    # Extraction Min
                    temp_min_span = cell.find('span', string=lambda s: s and 'min' in s)
                    temp_min = None
                    if temp_min_span:
                        temp_min_text = temp_min_span.get_text(strip=True).replace('min', '').replace('°', '').replace('\xa0', '')
                        temp_min = float(temp_min_text)

                    # --- Extraction Précipitations et Probabilité ---
                    precip = 0.0
                    prob_precip = 0
                    
                    # 1. Volume de pluie (mm)
                    precip_label = cell.find('span', string=lambda s: s and 'Précipitations' in s)
                    if precip_label:
                        val_span = precip_label.find_next_sibling('span', class_='fw-bold')
                        if val_span:
                            val_text = val_span.get_text(strip=True).replace('\xa0', ' ')
                            if 'à' in val_text:
                                # Si "1 à 2", on garde le 2 (la pire condition)
                                precip = float(val_text.split('à')[-1].strip())
                            else:
                                try: precip = float(val_text)
                                except ValueError: pass

                    # 2. Probabilité (%)
                    prob_label = cell.find('span', string=lambda s: s and 'Probabilité' in s)
                    if prob_label:
                        prob_text = prob_label.get_text(strip=True).replace('Probabilité :', '').replace('%', '').strip()
                        try: prob_precip = int(prob_text)
                        except ValueError: pass
                    # -----------------------------------------------------------

                    # Le jour 0 est aujourd'hui, jour 1 est demain, etc.
                    forecast_date = datetime.now() + timedelta(days=index)
                    
                    data["daily"].append(
                        Forecast(
                            datetime=forecast_date.isoformat(),
                            condition=ha_condition,
                            native_temperature=temp_max,
                            native_templow=temp_min,
                            native_precipitation=precip,
                            precipitation_probability=prob_precip
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
        heure_index = 0
        
        for cell in cells:
            try:
                # 1. Vérifier s'il y a une icône météo (Si non, on ignore la cellule)
                img = cell.find('img')
                if not img or 'alt' not in img.attrs:
                    continue

                # 2. Chercher la température (Un texte contenant "°" mais pas "min")
                h_temp = None
                spans = cell.find_all('span')
                for span in spans:
                    texte = span.get_text(strip=True)
                    if '°' in texte and len(texte) <= 4 and 'min' not in texte:
                        try:
                            h_temp = float(texte.replace('°', '').replace('C', '').strip())
                            break
                        except ValueError:
                            continue
                            
                # 3. Si on a trouvé une température, on assemble la prévision
                if h_temp is not None:
                    cond_text = img['alt'].lower()
                    h_cond = get_ha_condition(cond_text)

                    # Réinitialisation des variables pour chaque heure
                    h_hum = h_precip = h_prob = h_vent = h_raf = None

                    # Humidité (On ignore la casse H/h)
                    hum_img = cell.find("img", alt=lambda x: x and "umidité" in x.lower())
                    if hum_img and hum_img.find_parent("div"):
                        h_span = hum_img.find_parent("div").find("span", class_="fw-bold")
                        if h_span:
                            try: h_hum = float(h_span.text.strip())
                            except ValueError: pass
                    
                    # --- Précipitations (mm), Probabilité (%), Vent et Rafales ---
                    # On parcourt chaque petit bloc de détail de l'heure
                    for div in cell.find_all("div", class_="showDetailsBtn"):
                        div_text = div.get_text(separator=" ", strip=True).lower()
                        
                        # 1. Précipitations (mm) - La valeur est en gras
                        if "précipitation" in div_text and "mm" in div_text:
                            v_span = div.find("span", class_="fw-bold")
                            if v_span:
                                try: h_precip = float(v_span.text.replace(',', '.').strip())
                                except ValueError: pass
                                
                        # 2. Probabilité (%) - Attention, pas de gras et dans le même bloc que la pluie !
                        if "probabilité" in div_text:
                            # On cherche simplement n'importe quel span qui contient le signe "%"
                            for s in div.find_all("span"):
                                if "%" in s.text:
                                    try: 
                                        h_prob = float(s.text.replace('%', '').strip())
                                        break # On a trouvé, on arrête de chercher dans les spans
                                    except ValueError: pass

                        # 3. Vent et Rafales
                        if "km/h" in div_text:
                            # Vent Moyen (Toujours en gras)
                            v_span = div.find("span", class_="fw-bold")
                            if v_span:
                                try: h_vent = float(v_span.text.replace(',', '.').strip())
                                except ValueError: pass
                                
                            # Rafales (Dernier nombre avant un "km/h")
                            div_spans = div.find_all("span")
                            for s in div_spans:
                                txt = s.get_text(strip=True).lower()
                                if "km/h" in txt and len(txt) > 4: # Évite le span qui contient juste "km/h" sans chiffre
                                    try: h_raf = float(txt.replace("km/h", "").strip())
                                    except ValueError: pass

                    forecast_time = temps_actuel + timedelta(hours=heure_index)
                    data["hourly"].append(
                        Forecast(
                            datetime=forecast_time.isoformat(),
                            condition=h_cond,
                            native_temperature=h_temp,
                            humidity=h_hum,
                            native_wind_speed=h_vent,
                            native_wind_gust_speed=h_raf,
                            native_precipitation=h_precip,
                            precipitation_probability=h_prob
                        )
                    )
                    
                    # La première colonne de la page horaire devient notre "Current" (Météo actuelle)
                    if heure_index == 0:
                        data["current"] = {
                            "temp": h_temp,
                            "condition": h_cond,
                            "humidity": h_hum,
                            "wind_speed": h_vent,
                            "wind_gust": h_raf,
                            "precipitation": h_precip,
                            "prob_precip": h_prob
                        }
                    
                    heure_index += 1 # On passe à l'heure suivante
                    
            except Exception as e:
                _LOGGER.debug("Cellule ignorée : %s", e)
                continue

        return data

    except Exception as e:
        raise UpdateFailed(f"Erreur lors du scraping de la météo : {e}")

def get_ha_condition(text):
    """Traduit les alt images en conditions Home Assistant."""
    if "ciel clair" in text: return "clear-night"
    if "soleil" in text or "dégagé" in text or "ensoleillé" in text: return "sunny"
    if "orage" in text and ("pluie" in text or "averse" in text): return "lightning-rainy"
    if "neige" in text and ("pluie" in text or "averse" in text): return "snowy-rainy"
    if "forte" in text and ("pluie" in text or "averse" in text): return "pouring"
    if "pluie" in text or "averse" in text: return "rainy"
    if "orage" in text: return "lightning"
    if "neige" in text: return "snowy"
    if "brouillard" in text: return "fog"
    if "grêle" in text: return "hail"
    if "peu" in text or "partiellement" in text: return "partlycloudy"
    if "venteux" in text and "nuageux" in text: return "windy-variant"
    if "nuageux" in text: return "cloudy"
    if "venteux" in text: return "windy"
    return "cloudy"

class MeteoAgricoleWeather(CoordinatorEntity, WeatherEntity):
    """Représentation de l'entité Météo globale pour Home Assistant."""

    def __init__(self, coordinator, name, lat, lon):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"meteo_agricole_{lat}_{lon}"
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
        self._attr_supported_features = WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY

    @property
    def condition(self):
        """Condition actuelle (icône principale)."""
        return self.coordinator.data["current"].get("condition")

    @property
    def native_temperature(self):
        """Température actuelle."""
        return self.coordinator.data["current"].get("temp")

    @property
    def native_humidity(self) -> float | None:
        """Retourne l'humidité."""
        return self.coordinator.data["current"].get("humidity")

    @property
    def native_wind_speed(self) -> float | None:
        """Retourne la vitesse du vent."""
        return self.coordinator.data["current"].get("wind_speed")

    @property
    def native_wind_gust_speed(self) -> float | None:
        """Retourne la vitesse des rafales."""
        return self.coordinator.data["current"].get("wind_gust")

    @property
    def native_precipitation(self): return self.coordinator.data["current"].get("precipitation")

    @property
    def precipitation_probability(self): return self.coordinator.data["current"].get("prob_precip")

    @property
    def extra_state_attributes(self):
        if self.coordinator.last_update_success:
            return {"Dernière synchro réussie": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
        return {}

    async def async_forecast_daily(self) -> list[Forecast]:
        """Retourne les prévisions sur 10 jours (Min/Max)."""
        return self.coordinator.data.get("daily", [])

    async def async_forecast_hourly(self) -> list[Forecast]:
        """Retourne les prévisions heure par heure."""
        return self.coordinator.data.get("hourly", [])
