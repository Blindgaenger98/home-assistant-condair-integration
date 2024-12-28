# custom_components/condair/config_flow.py

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import CondairApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid credentials."""


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input by doing a one-time login with an ephemeral session.
    If it fails, raise InvalidAuth.
    """
    async with aiohttp.ClientSession() as session:
        ephemeral_api = CondairApi(session=session)
        success = await ephemeral_api.authenticate(
            data[CONF_USERNAME], data[CONF_PASSWORD]
        )
    if not success:
        raise InvalidAuth

    return {"title": "Condair Integration"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Condair."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception in config flow")
                errors["base"] = "unknown"
            else:
                # Store username & password in the config entry
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
