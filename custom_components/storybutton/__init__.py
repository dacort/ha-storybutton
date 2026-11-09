"""The Storybutton integration."""

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS
from .storybutton import (
    DeviceDescription,
    Storybutton,
    StorybuttonConfig,
    async_fetch_device_description,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class StorybuttonRuntimeData:
    """Runtime data stored on the config entry."""

    client: Storybutton
    description: DeviceDescription | None


type StorybuttonConfigEntry = ConfigEntry[StorybuttonRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (legacy)."""
    return True


async def _async_describe(
    hass: HomeAssistant, host: str | None
) -> DeviceDescription | None:
    """Best-effort fetch of device.xml; None if the device is unreachable."""
    if not host:
        return None
    try:
        return await async_fetch_device_description(async_get_clientsession(hass), host)
    except Exception:  # noqa: BLE001 - unreachable / malformed device.xml is expected
        _LOGGER.debug("device.xml not reachable at %s", host, exc_info=True)
        return None


async def _async_backfill_identity(
    hass: HomeAssistant,
    entry: "StorybuttonConfigEntry",
    description: DeviceDescription | None,
) -> None:
    """Attach the stable UDN identity to a legacy entry, idempotently.

    Backfills ``entry.unique_id`` from the UDN (so DHCP discovery can match the
    device after an IP change) and rewrites both the entity registry unique_id and
    the device registry identifier from the legacy ``entry_id`` to the UDN *in
    place*, preserving the entity_id and avoiding a phantom duplicate device. All
    steps are no-ops once already applied, and are deferred gracefully when the
    device is unreachable (no UDN known yet).
    """
    if entry.unique_id is None and description is not None and description.udn:
        hass.config_entries.async_update_entry(entry, unique_id=description.udn)

    udn = entry.unique_id
    if not udn:
        return  # UDN unknown (device unreachable) — defer to a future load.

    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.unique_id == udn:
            continue  # already migrated
        if reg_entry.unique_id != entry.entry_id:
            continue  # not the legacy entry_id-based id we know how to migrate
        if ent_reg.async_get_entity_id(reg_entry.domain, DOMAIN, udn):
            continue  # a row already owns the target unique_id; don't collide
        _LOGGER.debug(
            "Migrating %s unique_id %s -> %s",
            reg_entry.entity_id,
            reg_entry.unique_id,
            udn,
        )
        ent_reg.async_update_entity(reg_entry.entity_id, new_unique_id=udn)

    # Re-key the device registry entry in place: the legacy device is identified
    # by (DOMAIN, entry_id); the live identity is (DOMAIN, udn). Renaming it
    # avoids orphaning the old device and spawning a duplicate. No-op once the
    # device already carries the UDN identity, and guarded against collisions.
    if udn == entry.entry_id:
        return  # nothing to migrate — identity is already the entry_id
    dev_reg = dr.async_get(hass)
    if dev_reg.async_get_device(identifiers={(DOMAIN, udn)}) is not None:
        return  # a device already owns the target identity; don't collide
    old_device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if old_device is None:
        return  # no legacy device to migrate
    _LOGGER.debug(
        "Migrating device %s identifier (%s, %s) -> (%s, %s)",
        old_device.id,
        DOMAIN,
        entry.entry_id,
        DOMAIN,
        udn,
    )
    dev_reg.async_update_device(old_device.id, new_identifiers={(DOMAIN, udn)})


async def async_migrate_entry(
    hass: HomeAssistant, entry: "StorybuttonConfigEntry"
) -> bool:
    """Migrate old config entries to the UDN-based identity (1.0 -> 1.1)."""
    if entry.version == 1 and entry.minor_version < 1:
        description = await _async_describe(hass, entry.data.get(CONF_HOST))
        await _async_backfill_identity(hass, entry, description)
        hass.config_entries.async_update_entry(entry, minor_version=1)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: "StorybuttonConfigEntry"
) -> bool:
    """Set up Storybutton from a config entry."""
    host = entry.data[CONF_HOST]
    description = await _async_describe(hass, host)

    # Opportunistic identity backfill: covers entries whose migration was
    # deferred (device was unreachable) and only became reachable now, and
    # legacy entries that just had their UDN set via reconfigure.
    await _async_backfill_identity(hass, entry, description)

    entry.runtime_data = StorybuttonRuntimeData(
        client=Storybutton(StorybuttonConfig(host)),
        description=description,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: "StorybuttonConfigEntry"
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: "StorybuttonConfigEntry",
    device_entry: DeviceEntry,
) -> bool:
    """Allow deleting a stale/orphaned device from the UI.

    A device is considered *live* when it carries the entry's current
    UDN-based identity ``(DOMAIN, unique_id or entry_id)``. The live device may
    not be removed (HA would just recreate it); any other device tied to this
    entry — e.g. one left orphaned by an in-place identity migration — can be
    deleted by the user.
    """
    live_identifier = config_entry.unique_id or config_entry.entry_id
    return (DOMAIN, live_identifier) not in device_entry.identifiers
