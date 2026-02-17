"""Platform for Storybutton integration."""

import logging

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from custom_components.storybutton.storybutton import (
    State,
    Storybutton,
    StorybuttonConfig,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant, config, async_add_entities, discovery_info=None
):
    """Set up the storybutton platform.
    Allows for a single device to be added in your configuration.yaml
    media_player:
      - platform: storybutton
        host: 192.168.7.38
    """
    host = config.get(CONF_HOST)
    name = config.get(CONF_NAME)
    _LOGGER.info(f"Setting up Storybutton {name}@{host}")
    if host is None:
        return

    device = StoryButtonEntity(hass, host, name)
    async_add_entities([device], update_before_add=True)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up a Storybutton entity."""
    name = config_entry.data[CONF_NAME]
    host = config_entry.data[CONF_HOST]

    device = StoryButtonEntity(hass, host, name, config_entry.entry_id)
    async_add_entities([device], update_before_add=True)


class StoryButtonEntity(MediaPlayerEntity):
    """Representation of a Storybutton that communicates with your local device."""

    def __init__(self, hass, host, name, unique_id=None):
        """Initialize the media player."""
        self.hass = hass  # Store hass reference
        self._name = name
        self._host = host
        self._attr_unique_id = unique_id
        self._state = STATE_OFF
        self._attr_volume_level = 0
        self._attr_media_title = ""
        self._supported_features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )

        self.sb_device = Storybutton(StorybuttonConfig(self._host))

    @property
    def name(self):
        """Return the name of the media player."""
        return self._name

    @property
    def state(self):
        """Return the state of the media player."""
        return self._state

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return self._supported_features

    async def async_update(self):
        """Fetch new state data for the media player.


        This is where you can query your device using REST (or other protocols)
        and update the internal state accordingly.
        """
        # Example (pseudo-code):
        # response = await your_async_http_get(f"http://{self._host}/status")
        # self._state = parse_state_from_response(response)
        _LOGGER.debug("Updating state for %s", self._name)
        # For now, we’ll just simulate a state update:
        self._state = STATE_IDLE

        if not await self.hass.async_add_executor_job(self.sb_device.get_power_status):
            self._state = STATE_OFF
            return

        self._state = STATE_ON

        # Retrieve latest data
        # Note that when SB changes episodes, there's a delay for some reason
        # So I think I need to increase the timeout of the `status` call
        # Or t least let it handle more than 1 failure :)
        try:
            await self.async_update_media_title()
            await self.async_update_volume()
            if self._name is None:
                self._name = self.sb_device.name()
            status = await self.hass.async_add_executor_job(self.sb_device.status)
            if status == State.PLAYING:
                self._state = STATE_PLAYING
            elif status == State.PAUSED:
                self._state = STATE_PAUSED
        except Exception as exception_instance:  # pylint: disable=broad-except
            # TODO: Remove this or handle the NewConnectionError(urllib3.connection.HTTPConnection object) as this may be expected
            _LOGGER.error(exception_instance)
            self._state = STATE_OFF

    async def async_media_play(self):
        """Send play command to media player."""
        await self.hass.async_add_executor_job(self.sb_device.play)
        self._state = STATE_PLAYING

    async def async_media_pause(self):
        """Send pause command to media player."""
        await self.hass.async_add_executor_job(self.sb_device.pause)
        self._state = STATE_PAUSED

    async def async_media_stop(self):
        """Send stop command to media player."""
        await self.hass.async_add_executor_job(self.sb_device.pause)
        self._state = STATE_IDLE

    async def async_update_volume(self):
        self._attr_volume_level = (
            await self.hass.async_add_executor_job(self.sb_device.get_volume)
        ) / 100
        _LOGGER.debug(self._attr_volume_level)

    async def async_volume_up(self):
        """Send stop command."""
        self._attr_volume_level = await self.hass.async_add_executor_job(
            self.sb_device.volume_up
        )

    async def async_volume_down(self):
        """Send stop command."""
        self._attr_volume_level = await self.hass.async_add_executor_job(
            self.sb_device.volume_down
        )

    async def async_set_volume_level(self, volume):
        """Send set volume command."""
        await self.hass.async_add_executor_job(
            self.sb_device.set_volume, int(volume * 100)
        )

    async def async_mute_volume(self, mute):
        """Send mute command."""
        if mute:
            await self.hass.async_add_executor_job(self.sb_device.mute)
            self._attr_is_volume_muted = True
        else:
            await self.hass.async_add_executor_job(self.sb_device.unmute)
            self._attr_is_volume_muted = False

    async def async_update_media_title(self):
        self._attr_media_title = await self.hass.async_add_executor_job(
            self.sb_device.title
        )
        _LOGGER.debug(self._attr_media_title)
