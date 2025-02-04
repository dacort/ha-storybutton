from enum import Enum
import upnpclient
import requests

class State(Enum):
    UNKNOWN = 0
    OFF = 1
    ON = 2
    PLAYING = 3
    PAUSED = 4

class Storybutton:
    """A utility to interact with the Storybutton"""
    def __init__(self, host: str) -> None:
        self._host = host
        self._endpoint = f"http://{host}"

        # We don't initialize this here b/c it makes a sync call and HA gets mad
        self._upnp_client = None
    
    @property
    def upnp_client(self):
        if not self._upnp_client:
            self._upnp_client = upnpclient.Device(f"{self._endpoint}/device.xml")
        
        return self._upnp_client
    
    def get_power_status(self) -> bool:
        try:
            requests.get(self._endpoint, timeout=3)
            return True
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            return False
    
    def status(self) -> State:
        """Query the device for its status, if none, it's off"""
        if not self.get_power_status():
            return State.OFF

        # The device is up, so get the transport info
        resp = self.upnp_client.AVTransport.GetTransportInfo(InstanceID=0)
        current_state = resp.get('CurrentTransportState', None)
        if current_state == 'PAUSED_PLAYBACK':
            return State.PAUSED
        elif current_state == 'PLAYING':
            return State.PLAYING
        else:
            return State.UNKNOWN
    
    def name(self):
        return self.upnp_client.friendly_name
    
    def volume_up(self) -> int:
        current_volume = self.get_volume()
        if current_volume < 100:
            self.upnp_client.RenderingControl.SetVolume(InstanceID=0, Channel='Master', DesiredVolume=current_volume+1)
            return current_volume+1
        else:
            return current_volume
    
    def volume_down(self) -> int:
        current_volume = self.get_volume()
        if current_volume > 0:
            self.upnp_client.RenderingControl.SetVolume(InstanceID=0, Channel='Master', DesiredVolume=current_volume-1)
            return current_volume-1
        else:
            return current_volume
    
    def get_volume(self) -> int:
        """Returns the current volume, a value between 0 and 100"""
        resp = self.upnp_client.RenderingControl.GetVolume(InstanceID=0,Channel="Master")
        if 'CurrentVolume' not in resp:
            raise Exception("No volume returned from device: ", resp)
        
        return resp.get('CurrentVolume')

    def set_volume(self, desired_volume: int):
        self.upnp_client.RenderingControl.SetVolume(InstanceID=0, Channel='Master', DesiredVolume=desired_volume)

    def play(self):
        self.upnp_client.AVTransport.Play(InstanceID=0, Speed='1')

    def pause(self):
        self.upnp_client.AVTransport.Pause(InstanceID=0)
    
    def mute(self):
        self.upnp_client.RenderingControl.SetMute(InstanceID=0, Channel='Master', DesiredMute="1")

    def unmute(self):
        self.upnp_client.RenderingControl.SetMute(InstanceID=0, Channel='Master', DesiredMute="0")

    def title(self):
        try:
            playing_endpoint = f"{self._endpoint}/php/playing.php"
            resp = requests.get(playing_endpoint)
            return resp.json().get('name')
        except Exception:
            return ""