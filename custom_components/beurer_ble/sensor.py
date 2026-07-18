"""Sensor platform for the Beurer BLE (BF720) integration — one device per user."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BeurerConfigEntry
from .const import CONF_ADDRESS, CONF_NAME, CONF_USER_INDEX, CONF_USERS, DOMAIN
from .coordinator import BeurerCoordinator
from .parser import Measurement


@dataclass(frozen=True, kw_only=True)
class BeurerSensorEntityDescription(SensorEntityDescription):
    """Describes a Beurer sensor, with an extractor for the Measurement."""

    value_fn: Callable[[Measurement], float | int | None]


SENSORS: tuple[BeurerSensorEntityDescription, ...] = (
    BeurerSensorEntityDescription(
        key="weight",
        translation_key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda m: m.weight_kg,
    ),
    BeurerSensorEntityDescription(
        key="body_fat",
        translation_key="body_fat",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:percent",
        value_fn=lambda m: m.fat_pct,
    ),
    BeurerSensorEntityDescription(
        key="muscle",
        translation_key="muscle",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:arm-flex",
        value_fn=lambda m: m.muscle_pct,
    ),
    BeurerSensorEntityDescription(
        key="body_water",
        translation_key="body_water",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:water-percent",
        value_fn=lambda m: m.water_pct,
    ),
    BeurerSensorEntityDescription(
        key="bmi",
        translation_key="bmi",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:human",
        value_fn=lambda m: m.bmi,
    ),
    BeurerSensorEntityDescription(
        key="basal_metabolism",
        translation_key="basal_metabolism",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda m: m.bmr_kcal,
    ),
    BeurerSensorEntityDescription(
        key="muscle_mass",
        translation_key="muscle_mass",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda m: m.muscle_mass_kg,
    ),
    BeurerSensorEntityDescription(
        key="water_mass",
        translation_key="water_mass",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda m: m.water_mass_kg,
    ),
    BeurerSensorEntityDescription(
        key="soft_lean_mass",
        translation_key="soft_lean_mass",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda m: m.soft_lean_mass_kg,
    ),
    BeurerSensorEntityDescription(
        key="impedance",
        translation_key="impedance",
        native_unit_of_measurement="Ω",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:omega",
        value_fn=lambda m: m.impedance_ohm,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BeurerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one device (with the full sensor set) per configured user."""
    coordinator = entry.runtime_data
    address = entry.data[CONF_ADDRESS]

    entities: list[BeurerSensor] = []
    for user in entry.options.get(CONF_USERS, []):
        for description in SENSORS:
            entities.append(BeurerSensor(coordinator, address, user, description))
    async_add_entities(entities)


class BeurerSensor(
    PassiveBluetoothCoordinatorEntity[BeurerCoordinator], SensorEntity
):
    """A single body-composition metric for one on-scale user."""

    _attr_has_entity_name = True
    entity_description: BeurerSensorEntityDescription

    def __init__(
        self,
        coordinator: BeurerCoordinator,
        address: str,
        user: dict,
        description: BeurerSensorEntityDescription,
    ) -> None:
        """Initialise the sensor bound to a user slot."""
        super().__init__(coordinator)
        self.entity_description = description
        self._user_index: int = user[CONF_USER_INDEX]
        self._attr_unique_id = f"{address}_{self._user_index}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{address}_{self._user_index}")},
            name=user.get(CONF_NAME) or f"Beurer BF720 user {self._user_index}",
            manufacturer="Beurer",
            model="BF720",
            via_device=(DOMAIN, address),
        )

    @property
    def native_value(self) -> float | int | None:
        """Return the current value for this metric, if a reading exists."""
        measurement = self.coordinator.data.get(self._user_index)
        if measurement is None:
            return None
        return self.entity_description.value_fn(measurement)
