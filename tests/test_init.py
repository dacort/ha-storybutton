"""Migration / identity-backfill tests (pytest-homeassistant-custom-component)."""

from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.storybutton import (
    async_migrate_entry,
    async_remove_config_entry_device,
)
from custom_components.storybutton.const import DOMAIN
from custom_components.storybutton.storybutton import DeviceDescription

_FETCH = "custom_components.storybutton.async_fetch_device_description"


def _legacy_entry(host: str) -> MockConfigEntry:
    """A pre-UDN entry: unique_id=None, minor_version=0."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=None,
        minor_version=0,
        data={CONF_HOST: host, CONF_NAME: "Amelia"},
    )


def _register_legacy_entity(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Register a media_player entity keyed by the legacy entry_id."""
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "media_player",
        DOMAIN,
        entry.entry_id,
        config_entry=entry,
        suggested_object_id="amelias_storybutton",
    )
    return "media_player.amelias_storybutton"


def _register_legacy_device(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Register a device keyed by the legacy entry_id, returning its device id."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Amelia's Storybutton",
    )
    return device.id


async def test_migration_backfills_identity_when_reachable(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """When the device is reachable, migration backfills the UDN and rewrites
    the entity unique_id in place while preserving the entity_id."""
    entry = _legacy_entry("192.168.7.48")
    entry.add_to_hass(hass)
    entity_id = _register_legacy_entity(hass, entry)

    with patch(_FETCH, return_value=device_description):
        assert await async_migrate_entry(hass, entry) is True

    assert entry.unique_id == device_description.udn
    assert entry.minor_version == 1

    ent = er.async_get(hass).async_get(entity_id)
    assert ent is not None  # entity_id preserved
    assert ent.unique_id == device_description.udn


async def test_migration_defers_when_unreachable(hass: HomeAssistant) -> None:
    """When the device is unreachable, migration leaves the entry working with
    its legacy identity and defers (no UDN yet)."""
    entry = _legacy_entry("192.168.7.99")  # stale IP, device not there
    entry.add_to_hass(hass)
    entity_id = _register_legacy_entity(hass, entry)

    with patch(_FETCH, side_effect=OSError("unreachable")):
        assert await async_migrate_entry(hass, entry) is True

    assert entry.unique_id is None  # deferred — no UDN known

    ent = er.async_get(hass).async_get(entity_id)
    assert ent is not None
    assert ent.unique_id == entry.entry_id  # legacy unique_id untouched


async def test_migration_renames_device_in_place(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """Migration re-keys the existing device from (DOMAIN, entry_id) to
    (DOMAIN, udn) in place rather than orphaning it and spawning a duplicate."""
    entry = _legacy_entry("192.168.7.48")
    entry.add_to_hass(hass)
    _register_legacy_entity(hass, entry)
    device_id = _register_legacy_device(hass, entry)

    with patch(_FETCH, return_value=device_description):
        assert await async_migrate_entry(hass, entry) is True

    dev_reg = dr.async_get(hass)
    # The same device row is reused, now keyed by the UDN.
    migrated = dev_reg.async_get_device(identifiers={(DOMAIN, device_description.udn)})
    assert migrated is not None
    assert migrated.id == device_id
    # No orphaned device left behind under the legacy entry_id.
    assert dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)}) is None
    # Exactly one device remains for the entry.
    assert len(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)) == 1


async def test_migration_device_rename_skips_on_collision(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """If a device already owns the UDN identity, the legacy device is left
    untouched (no clobbering of the live device)."""
    entry = _legacy_entry("192.168.7.48")
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    legacy = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Legacy",
    )
    live = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_description.udn)},
        name="Live",
    )

    with patch(_FETCH, return_value=device_description):
        assert await async_migrate_entry(hass, entry) is True

    # Both devices remain; the legacy one keeps its identifier.
    assert dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)}).id == (
        legacy.id
    )
    assert dev_reg.async_get_device(
        identifiers={(DOMAIN, device_description.udn)}
    ).id == (live.id)


async def test_remove_config_entry_device(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """A stale device may be removed; the live (UDN-keyed) device may not."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_description.udn,
        minor_version=1,
        data={CONF_HOST: "192.168.7.48", CONF_NAME: "Amelia"},
    )
    entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    live = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_description.udn)},
        name="Live",
    )
    stale = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Stale",
    )

    assert await async_remove_config_entry_device(hass, entry, stale) is True
    assert await async_remove_config_entry_device(hass, entry, live) is False
