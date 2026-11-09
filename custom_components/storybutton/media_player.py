"""Platform for Storybutton integration."""

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .const import DOMAIN
from .storybutton import (
    DeviceDescription,
    State,
    Storybutton,
    StorybuttonConfig,
)

_LOGGER = logging.getLogger(__name__)

_SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
)


def _build_device_info(
    identifier: str,
    name: str | None,
    desc: DeviceDescription | None,
    mac: str | None,
) -> DeviceInfo:
    """Assemble the device registry entry.

    Identity/metadata come from device.xml; the real network MAC (for the
    registry connection) comes from DHCP discovery and is stored on the entry.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name=name,
        manufacturer="Storybutton",
    )
    if mac:
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    if desc:
        if desc.manufacturer:
            info["manufacturer"] = desc.manufacturer
        if desc.model:
            info["model"] = desc.model
        if desc.sw_version:
            info["sw_version"] = desc.sw_version
    return info


async def async_setup_platform(
    hass: HomeAssistant, config, async_add_entities, discovery_info=None
):
    """Set up the storybutton platform from legacy YAML.

    media_player:
      - platform: storybutton
        host: 192.168.7.38
    """
    host = config.get(CONF_HOST)
    name = config.get(CONF_NAME)
    _LOGGER.info("Setting up Storybutton %s@%s", name, host)
    if host is None:
        return

    client = Storybutton(StorybuttonConfig(host))
    async_add_entities(
        [StoryButtonEntity(hass, client, name, None, None)],
        update_before_add=True,
    )


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up a Storybutton entity from a config entry."""
    data = config_entry.runtime_data
    name = config_entry.data[CONF_NAME]
    # Prefer the stable UDN; fall back to entry_id for not-yet-migrated entries.
    unique_id = config_entry.unique_id or config_entry.entry_id
    device_info = _build_device_info(
        unique_id, name, data.description, config_entry.data.get(CONF_MAC)
    )

    async_add_entities(
        [StoryButtonEntity(hass, data.client, name, unique_id, device_info)],
        update_before_add=True,
    )


class StoryButtonEntity(MediaPlayerEntity):
    """Representation of a Storybutton that communicates with your local device."""

    _attr_supported_features = _SUPPORTED_FEATURES

    def __init__(self, hass, client, name, unique_id, device_info=None):
        """Initialize the media player."""
        self.hass = hass  # available before the entity is registered
        self._client = client
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info
        self._attr_state = MediaPlayerState.OFF
        self._attr_volume_level = 0
        self._attr_media_title = ""

    async def async_update(self):
        """Fetch new state data for the media player."""
        _LOGGER.debug("Updating state for %s", self._attr_name)

        if not await self.hass.async_add_executor_job(self._client.get_power_status):
            self._attr_state = MediaPlayerState.OFF
            return

        self._attr_state = MediaPlayerState.ON

        # Note that when SB changes episodes, there's a delay for some reason
        # So I think I need to increase the timeout of the `status` call
        # Or at least let it handle more than 1 failure :)
        try:
            await self.async_update_media_title()
            await self.async_update_volume()
            if self._attr_name is None:
                self._attr_name = await self.hass.async_add_executor_job(
                    self._client.name
                )
            status = await self.hass.async_add_executor_job(self._client.status)
            if status == State.PLAYING:
                self._attr_state = MediaPlayerState.PLAYING
            elif status == State.PAUSED:
                self._attr_state = MediaPlayerState.PAUSED
        except Exception as exception_instance:  # pylint: disable=broad-except
            _LOGGER.error(exception_instance)
            self._attr_state = MediaPlayerState.OFF

    async def async_media_play(self):
        """Send play command to media player."""
        await self.hass.async_add_executor_job(self._client.play)
        self._attr_state = MediaPlayerState.PLAYING

    async def async_media_pause(self):
        """Send pause command to media player."""
        await self.hass.async_add_executor_job(self._client.pause)
        self._attr_state = MediaPlayerState.PAUSED

    async def async_media_stop(self):
        """Send stop command to media player."""
        await self.hass.async_add_executor_job(self._client.pause)
        self._attr_state = MediaPlayerState.IDLE

    async def async_update_volume(self):
        """Refresh the cached volume level."""
        self._attr_volume_level = (
            await self.hass.async_add_executor_job(self._client.get_volume)
        ) / 100
        _LOGGER.debug(self._attr_volume_level)

    async def async_volume_up(self):
        """Step the volume up."""
        self._attr_volume_level = await self.hass.async_add_executor_job(
            self._client.volume_up
        )

    async def async_volume_down(self):
        """Step the volume down."""
        self._attr_volume_level = await self.hass.async_add_executor_job(
            self._client.volume_down
        )

    async def async_set_volume_level(self, volume):
        """Set the volume to an absolute level."""
        await self.hass.async_add_executor_job(
            self._client.set_volume, int(volume * 100)
        )

    async def async_mute_volume(self, mute):
        """Mute or unmute the device."""
        if mute:
            await self.hass.async_add_executor_job(self._client.mute)
            self._attr_is_volume_muted = True
        else:
            await self.hass.async_add_executor_job(self._client.unmute)
            self._attr_is_volume_muted = False

    async def async_update_media_title(self):
        """Refresh the cached media title."""
        self._attr_media_title = await self.hass.async_add_executor_job(
            self._client.title
        )
        _LOGGER.debug(self._attr_media_title)
