"""Migration / identity-backfill tests (pytest-homeassistant-custom-component)."""

from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.storybutton import async_migrate_entry
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
