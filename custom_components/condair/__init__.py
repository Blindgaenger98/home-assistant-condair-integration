"""Initialize the Condair integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import CondairApi

_LOGGER = logging.getLogger(__name__)

DOMAIN = "condair"

# We want both sensor and humidifier
PLATFORMS = [Platform.SENSOR, Platform.HUMIDIFIER]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """For config-flow-only integrations, we often just return True here.
    If you had YAML-based config, you'd parse it here.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Condair from a config entry.
    1) Create an API instance.
    2) Authenticate with the user's credentials.
    3) Store the API so sensors/humidifiers can access it.
    4) Forward the setup to sensor/humidifier.
    """
    _LOGGER.debug("Setting up Condair entry: %s", entry.as_dict())

    # We assume 'username' and 'password' are stored in entry.data from config_flow
    username = entry.data.get("username")
    password = entry.data.get("password")
    if not username or not password:
        _LOGGER.error("No credentials found in config entry data; cannot authenticate.")
        return False

    api = CondairApi()
    success = await api.authenticate(username, password)
    if not success:
        _LOGGER.error("Failed to authenticate with Condair API; setup aborted.")
        return False

    # If we reach here, authentication succeeded, so we store the API instance
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = api

    # Forward the setup to sensor/humidifier
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Condair integration.
    1) Close the API session if we own it.
    2) Unload each platform.
    """
    api: CondairApi = hass.data[DOMAIN].pop(entry.entry_id, None)
    if api:
        await api.close_session()

    # Unload sensor/humidifier platforms
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
