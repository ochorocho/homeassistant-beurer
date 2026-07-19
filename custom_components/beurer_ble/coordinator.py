"""Active-connection Bluetooth coordinator for the Beurer BF720."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CoreState, HomeAssistant, callback

from . import parser
from .const import POLL_MIN_INTERVAL_SECONDS
from .device import UserCredential, async_read_measurements

_LOGGER = logging.getLogger(__name__)


class BeurerCoordinator(ActiveBluetoothDataUpdateCoordinator[dict[int, parser.Measurement]]):
    """Connects to the scale on advertisement and reads each configured user."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        users: list[UserCredential],
    ) -> None:
        """Initialise the coordinator for one scale."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=address,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_poll,
            mode=BluetoothScanningMode.ACTIVE,
            connectable=True,
        )
        self._users = users
        self.data: dict[int, parser.Measurement] = {}

    @callback
    def _needs_poll(
        self, service_info: BluetoothServiceInfoBleak, seconds_since_last_poll: float | None
    ) -> bool:
        return (
            self.hass.state is CoreState.running
            and (seconds_since_last_poll is None or seconds_since_last_poll > POLL_MIN_INTERVAL_SECONDS)
            and bool(
                async_ble_device_from_address(self.hass, service_info.device.address, connectable=True)
            )
        )

    async def _async_poll(
        self, service_info: BluetoothServiceInfoBleak
    ) -> dict[int, parser.Measurement]:
        ble_device = (
            async_ble_device_from_address(self.hass, service_info.device.address, connectable=True)
            or service_info.device
        )
        fresh = await async_read_measurements(ble_device, self._users)

        # Merge into existing data, keeping the newest reading per user.
        merged = dict(self.data)
        for index, measurement in fresh.items():
            prev = merged.get(index)
            if prev is None or parser.newer(measurement.timestamp, prev.timestamp):
                merged[index] = measurement
        return merged
