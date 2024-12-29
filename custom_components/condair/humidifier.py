from datetime import datetime, timedelta
import logging

from homeassistant.components.humidifier import HumidifierEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN
from .api import CondairApi

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.components.humidifier import HumidifierEntityFeature
except ImportError:

    class HumidifierEntityFeature:
        NONE = 0
        MODES = 1
        TARGET_HUMIDITY = 2


if not hasattr(HumidifierEntityFeature, "TARGET_HUMIDITY"):
    HumidifierEntityFeature.TARGET_HUMIDITY = 2
    _LOGGER.warning("Fallback for TARGET_HUMIDITY feature used.")

SUPPORT_TARGET_HUMIDITY = {HumidifierEntityFeature.TARGET_HUMIDITY}

# Cooldown period in seconds
UPDATE_COOLDOWN = 30


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Condair humidifiers from config entry."""
    api: CondairApi = hass.data[DOMAIN][entry.entry_id]
    devices = await api.get_devices()
    entities = []

    for device in devices:
        unique_id = device.get("uniqueId")
        device_name = device.get("instanceName", "Unnamed Humidifier")

        if not unique_id:
            _LOGGER.warning(
                "Device %s has no uniqueId; skipping humidifier entity.", device_name
            )
            continue

        try:
            actions = await api.get_actions(unique_id)
            if not actions:
                _LOGGER.info(
                    "Device %s has no actions available; skipping.", device_name
                )
                continue

            entities.append(CondairHumidifierEntity(api, unique_id, device_name))
        except Exception as e:
            _LOGGER.error(
                "Error fetching actions for device %s: %s", device_name, str(e)
            )

    if entities:
        _LOGGER.info("Adding %d humidifier entities.", len(entities))
    else:
        _LOGGER.warning("No humidifier entities added; no valid devices found.")

    async_add_entities(entities, update_before_add=True)


class CondairHumidifierEntity(HumidifierEntity):
    """Representation of a Condair humidifier."""

    def __init__(self, api: CondairApi, unique_id: str, device_name: str):
        self._api = api
        self._unique_id = unique_id
        self._device_name = device_name

        self._attr_name = f"{device_name} Humidifier"
        self._attr_unique_id = f"condair_{unique_id}_humidifier"
        self._attr_supported_features = SUPPORT_TARGET_HUMIDITY

        self._is_on = False
        self._current_humidity = 0
        self._target_humidity = 50
        self._last_set_humidity = 50  # Default last set humidity
        self._current_temp = None

        self._last_update = datetime.min  # For cooldown

    async def async_update(self) -> None:
        """Fetch the latest data from the API."""
        now = datetime.now()

        if (now - self._last_update) < timedelta(seconds=UPDATE_COOLDOWN):
            _LOGGER.debug(
                "Skipping update for %s due to cooldown. Last update was at %s.",
                self._device_name,
                self._last_update,
            )
            return

        data = await self._api.get_latest_datapoints(self._unique_id)

        if "is_on" in data:
            self._is_on = data["is_on"]

        if "target_humidity" in data:
            target_humidity = int(data["target_humidity"])
            if self._is_on:
                self._target_humidity = target_humidity
                self._last_set_humidity = target_humidity
            # If the device is off and the target is 0, retain the last set humidity
            elif target_humidity == 0:
                _LOGGER.debug(
                    "Retaining last set humidity %s for %s as the device is off.",
                    self._last_set_humidity,
                    self._device_name,
                )
            else:
                self._target_humidity = target_humidity

        if "humidity_avg" in data:
            self._current_humidity = int(data["humidity_avg"])
        if "temperature_avg" in data:
            self._current_temp = float(data["temperature_avg"])

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        success = await self._api.set_on_off(self._unique_id, True)
        if success:
            self._is_on = True
            self._target_humidity = self._last_set_humidity  # Restore last set humidity
            self._last_update = datetime.now()

    async def async_turn_off(self, **kwargs) -> None:
        success = await self._api.set_on_off(self._unique_id, False)
        if success:
            self._is_on = False
            self._last_update = datetime.now()

    @property
    def current_humidity(self) -> int | None:
        return self._current_humidity

    @property
    def target_humidity(self) -> int | None:
        return self._target_humidity

    async def async_set_humidity(self, humidity: int) -> None:
        success = await self._api.set_humidity_reference(self._unique_id, humidity)
        if success:
            self._target_humidity = humidity
            self._last_set_humidity = humidity  # Update last set humidity
            self._last_update = datetime.now()

    @property
    def extra_state_attributes(self) -> dict:
        """Optional extra attributes."""
        attrs = {}
        if self._current_temp is not None:
            attrs["current_temperature"] = self._current_temp
        return attrs

    @property
    def device_info(self):
        """Device info for Home Assistant."""
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._device_name,
            "manufacturer": "Condair",
            "model": "HumiLife",  # Updated model
        }
