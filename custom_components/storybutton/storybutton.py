from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import requests
import upnpclient


class State(Enum):
    UNKNOWN = 0
    OFF = 1
    ON = 2
    PLAYING = 3
    PAUSED = 4


@dataclass
class StorybuttonConfig:
    """Configuration for Storybutton instance."""

    host: str
    request_timeout: int = 3
    http_client: requests.sessions.Session = requests.Session()
    upnp_factory: Callable[[str], upnpclient.Device] = upnpclient.Device


class Storybutton:
    """A utility to interact with the Storybutton device."""

    def __init__(self, config: StorybuttonConfig) -> None:
        """
        Initialize a new Storybutton instance.

        Args:
            config: StorybuttonConfig instance containing configuration
        """
        self._config = config
        self._endpoint = f"http://{config.host}"
        self._upnp_client: Optional[upnpclient.upnp.Device] = None
        self._http_client = config.http_client

    @property
    def upnp_client(self) -> upnpclient.Device:
        """
        Lazy initialization of UPnP client.

        Returns:
            UPnPDevice: The initialized UPnP client
        """
        if not self._upnp_client:
            self._upnp_client = self._config.upnp_factory(
                f"{self._endpoint}/device.xml"
            )
        return self._upnp_client

    def get_power_status(self) -> bool:
        """
        Check if the device is powered on and responding.

        Returns:
            bool: True if device is responding, False otherwise
        """
        try:
            self._http_client.get(self._endpoint, timeout=self._config.request_timeout)
            return True
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            return False

    def status(self) -> State:
        """
        Query the device for its current playback status.

        Returns:
            State: Current state of the device
        """
        if not self.get_power_status():
            return State.OFF

        return self._get_play_status_from_api()

    def _get_play_status_from_upnp(self):
        """Uses upnp to get the current play state.

        Unfortunately, calling `AVTransport.GetTransportInfo` can sometimes
        result in the Storybutton crashing, specifically:
        - When it's trying to update
        """
        resp = self.upnp_client.AVTransport.GetTransportInfo(InstanceID=0)
        current_state = resp.get("CurrentTransportState")

        return {"PAUSED_PLAYBACK": State.PAUSED, "PLAYING": State.PLAYING}.get(
            current_state, State.UNKNOWN
        )

    def _get_play_status_from_api(self):
        """Gets the current play state from the device's API"""
        status = self._playing_php_response()

        if not status or status.get("result") == "fail":
            return State.UNKNOWN

        current_status = status.get("chStatus", "").replace("Play state: ", "")
        return {"paused": State.PAUSED, "playing": State.PLAYING}.get(
            current_status, State.UNKNOWN
        )

    def name(self) -> str:
        """Get the friendly name of the device."""
        return self.upnp_client.friendly_name

    def get_volume(self) -> int:
        """
        Get the current volume level.

        Returns:
            int: Current volume (0-100)

        Raises:
            Exception: If volume information is not available
        """
        resp = self.upnp_client.RenderingControl.GetVolume(
            InstanceID=0, Channel="Master"
        )
        if "CurrentVolume" not in resp:
            raise Exception("No volume returned from device: ", resp)

        return resp["CurrentVolume"]

    def set_volume(self, desired_volume: int) -> None:
        """Set the volume to a specific level."""
        self.upnp_client.RenderingControl.SetVolume(
            InstanceID=0,
            Channel="Master",
            DesiredVolume=max(0, min(100, desired_volume)),
        )

    def volume_up(self) -> int:
        """
        Increase volume by one step.

        Returns:
            int: New volume level
        """
        current_volume = self.get_volume()
        if current_volume < 100:
            self.set_volume(current_volume + 1)
            return current_volume + 1
        return current_volume

    def volume_down(self) -> int:
        """
        Decrease volume by one step.

        Returns:
            int: New volume level
        """
        current_volume = self.get_volume()
        if current_volume > 0:
            self.set_volume(current_volume - 1)
            return current_volume - 1
        return current_volume

    def play(self) -> None:
        """Start playback."""
        self.upnp_client.AVTransport.Play(InstanceID=0, Speed="1")

    def pause(self) -> None:
        """Pause playback."""
        self.upnp_client.AVTransport.Pause(InstanceID=0)

    def mute(self) -> None:
        """Mute the device."""
        self.upnp_client.RenderingControl.SetMute(
            InstanceID=0, Channel="Master", DesiredMute="1"
        )

    def unmute(self) -> None:
        """Unmute the device."""
        self.upnp_client.RenderingControl.SetMute(
            InstanceID=0, Channel="Master", DesiredMute="0"
        )

    def title(self) -> str:
        """
        Get the currently playing title.

        Returns:
            str: Title of current content or empty string if unavailable
        """
        try:
            playing_endpoint = f"{self._endpoint}/php/playing.php"
            resp = self._http_client.get(playing_endpoint)
            return resp.json().get("name", "")
        except Exception:
            return ""

    def _playing_php_response(self) -> dict | None:
        """Returns the decoded response from the frontend's playing.php API

        e.g.
        {
            "name": "The Poison Type Dragon, The Corrupted Fairy Portal, and The Search for the Dragonlings - Cards of Power #26",
            "error": "n",
            "chStatus": "Play state: playing",
            "AddDelBtn": "?",
            "result": "success"
        }

        Returns:
            dict: JSON response
        """
        try:
            playing_endpoint = f"{self._endpoint}/php/playing.php"
            resp = self._http_client.get(playing_endpoint)
            return resp.json()
        except Exception:
            return None
