"""Sensor platform for the Condair integration."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN
from .api import CondairApi

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up temperature & humidity sensors for each Condair device."""
    api: CondairApi = hass.data[DOMAIN][entry.entry_id]
    devices = await api.get_devices()
    sensor_entities = []

    for device in devices:
        unique_id = device.get("uniqueId")
        device_name = device.get("instanceName", "Unnamed Device")

        if not unique_id:
            _LOGGER.warning(
                "Device %s missing uniqueId; skipping sensors.", device_name
            )
            continue

        try:
            datapoints = await api.get_latest_datapoints(unique_id)
            has_temp = datapoints["temperature_avg"] is not None
            has_humidity = datapoints["humidity_avg"] is not None

            if not has_temp and not has_humidity:
                _LOGGER.info(
                    "Device %s has no temperature or humidity data points; skipping.",
                    device_name,
                )
                continue

            if has_temp:
                sensor_entities.append(
                    CondairTemperatureSensor(api, unique_id, device_name)
                )
            if has_humidity:
                sensor_entities.append(
                    CondairHumiditySensor(api, unique_id, device_name)
                )
        except Exception as e:
            _LOGGER.error(
                "Error fetching datapoints for device %s: %s", device_name, str(e)
            )

    if sensor_entities:
        _LOGGER.info("Adding %d sensor entities.", len(sensor_entities))
    else:
        _LOGGER.warning("No sensor entities added; no valid devices found.")

    async_add_entities(sensor_entities, update_before_add=True)


class CondairTemperatureSensor(SensorEntity):
    """A sensor entity for temperature from Condair's latest datapoints."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, api: CondairApi, unique_id: str, device_name: str):
        self._api = api
        self._unique_id = unique_id
        self._device_name = device_name

        self._attr_name = f"{device_name} Temperature"
        self._attr_unique_id = f"condair_{unique_id}_temp"

        self._temp_value = None

    async def async_update(self) -> None:
        """Periodically fetch from api.get_latest_datapoints(uniqueId)."""
        data = await self._api.get_latest_datapoints(self._unique_id)
        self._temp_value = data.get("temperature_avg", None)

    @property
    def native_value(self):
        return self._temp_value

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._device_name,
            "manufacturer": "Condair",
        }


class CondairHumiditySensor(SensorEntity):
    """A sensor entity for humidity from Condair's latest datapoints."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, api: CondairApi, unique_id: str, device_name: str):
        self._api = api
        self._unique_id = unique_id
        self._device_name = device_name

        self._attr_name = f"{device_name} Humidity"
        self._attr_unique_id = f"condair_{unique_id}_humidity"

        self._humidity_value = None

    async def async_update(self) -> None:
        data = await self._api.get_latest_datapoints(self._unique_id)
        self._humidity_value = data.get("humidity_avg", None)

    @property
    def native_value(self):
        return self._humidity_value

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._device_name,
            "manufacturer": "Condair",
        }
