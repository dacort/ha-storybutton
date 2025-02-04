import pytest
from unittest.mock import Mock, create_autospec
import requests
import upnpclient
from typing import Tuple

from custom_components.storybutton.storybutton import Storybutton, StorybuttonConfig, State

@pytest.fixture
def mock_upnp() -> Mock:
    """Create a mock UPnP device with all required attributes and methods."""
    mock = create_autospec(upnpclient.Device)
    
    # Set up RenderingControl service
    mock.RenderingControl = Mock()
    mock.RenderingControl.GetVolume.return_value = {'CurrentVolume': 50}
    
    # Set up AVTransport service
    mock.AVTransport = Mock()
    mock.AVTransport.GetTransportInfo.return_value = {'CurrentTransportState': 'PLAYING'}
    
    # Set friendly name
    mock.friendly_name = "Test Device"
    
    return mock

@pytest.fixture
def mock_session() -> Mock:
    """Create a mock requests.sessions.Session ."""
    return create_autospec(requests.sessions.Session )

@pytest.fixture
def storybutton(mock_upnp: Mock, mock_session: Mock) -> Tuple[Storybutton, Mock, Mock]:
    """
    Create a Storybutton instance with mocked dependencies.
    
    Returns:
        Tuple containing:
        - Configured Storybutton instance
        - Mock UPnP device
        - Mock HTTP session
    """
    config = StorybuttonConfig(
        host="test-host",
        http_client=mock_session,
        upnp_factory=lambda _: mock_upnp
    )
    return Storybutton(config), mock_upnp, mock_session

class TestStorybutton:
    def test_init(self):
        """Test basic initialization without accessing UPnP client."""
        config = StorybuttonConfig(host="test-host")
        button = Storybutton(config)
        
        assert button._endpoint == "http://test-host"
        assert button._upnp_client is None
        assert button._config.request_timeout == 3  # default value

    def test_get_power_status_online(self, storybutton):
        """Test power status when device is online."""
        button, _, mock_session = storybutton
        mock_session.get.return_value = Mock(status_code=200)
        
        assert button.get_power_status() is True
        mock_session.get.assert_called_once_with(
            "http://test-host",
            timeout=3
        )

    def test_get_power_status_offline(self, storybutton):
        """Test power status when device is offline."""
        button, _, mock_session = storybutton
        mock_session.get.side_effect = requests.exceptions.Timeout()
        
        assert button.get_power_status() is False

    def test_status_device_off(self, storybutton):
        """Test status when device is powered off."""
        button, mock_upnp, mock_session = storybutton
        mock_session.get.side_effect = requests.exceptions.Timeout()
        
        assert button.status() == State.OFF
        # Verify we didn't try to access UPnP client
        mock_upnp.AVTransport.GetTransportInfo.assert_not_called()

    @pytest.mark.parametrize("transport_state,expected_state", [
        ('PLAYING', State.PLAYING),
        ('PAUSED_PLAYBACK', State.PAUSED),
        ('STOPPED', State.UNKNOWN),
        (None, State.UNKNOWN),
    ])
    def test_status_various_states(self, storybutton, transport_state, expected_state):
        """Test status for different transport states."""
        button, mock_upnp, mock_session = storybutton
        
        # Ensure device appears online
        mock_session.get.return_value = Mock(status_code=200)
        
        # Configure transport state
        mock_upnp.AVTransport.GetTransportInfo.return_value = {
            'CurrentTransportState': transport_state
        }
        
        assert button.status() == expected_state

    def test_volume_controls(self, storybutton):
        """Test volume control functions."""
        button, mock_upnp, _ = storybutton
        
        # Test get_volume
        mock_upnp.RenderingControl.GetVolume.return_value = {'CurrentVolume': 50}
        assert button.get_volume() == 50
        
        # Test volume_up
        new_volume = button.volume_up()
        assert new_volume == 51
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredVolume=51
        )
        
        # Test volume_down
        mock_upnp.RenderingControl.GetVolume.return_value = {'CurrentVolume': 51}
        new_volume = button.volume_down()
        assert new_volume == 50
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredVolume=50
        )

    def test_volume_limits(self, storybutton):
        """Test volume limits (0-100)."""
        button, mock_upnp, _ = storybutton
        
        # Test upper limit
        mock_upnp.RenderingControl.GetVolume.return_value = {'CurrentVolume': 100}
        assert button.volume_up() == 100
        mock_upnp.RenderingControl.SetVolume.assert_not_called()
        
        # Test lower limit
        mock_upnp.RenderingControl.GetVolume.return_value = {'CurrentVolume': 0}
        assert button.volume_down() == 0
        mock_upnp.RenderingControl.SetVolume.assert_not_called()

    def test_set_volume_limits(self, storybutton):
        """Test set_volume respects limits."""
        button, mock_upnp, _ = storybutton
        
        # Test above max
        button.set_volume(150)
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredVolume=100
        )
        
        # Test below min
        button.set_volume(-10)
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredVolume=0
        )

    def test_playback_controls(self, storybutton):
        """Test playback control functions."""
        button, mock_upnp, _ = storybutton
        
        button.play()
        mock_upnp.AVTransport.Play.assert_called_with(InstanceID=0, Speed='1')
        
        button.pause()
        mock_upnp.AVTransport.Pause.assert_called_with(InstanceID=0)

    def test_mute_controls(self, storybutton):
        """Test mute control functions."""
        button, mock_upnp, _ = storybutton
        
        button.mute()
        mock_upnp.RenderingControl.SetMute.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredMute="1"
        )
        
        button.unmute()
        mock_upnp.RenderingControl.SetMute.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredMute="0"
        )

    def test_title(self, storybutton):
        """Test title retrieval."""
        button, _, mock_session = storybutton
        
        # Test successful title retrieval
        mock_session.get.return_value.json.return_value = {'name': 'Test Track'}
        assert button.title() == 'Test Track'
        mock_session.get.assert_called_with("http://test-host/php/playing.php")
        
        # Test failed title retrieval
        mock_session.get.side_effect = Exception()
        assert button.title() == ""

    def test_get_volume_error(self, storybutton):
        """Test error handling in get_volume."""
        button, mock_upnp, _ = storybutton
        mock_upnp.RenderingControl.GetVolume.return_value = {}
        
        with pytest.raises(Exception) as exc_info:
            button.get_volume()
        assert "No volume returned from device" in str(exc_info.value)

    def test_name(self, storybutton):
        """Test device name retrieval."""
        button, mock_upnp, _ = storybutton
        mock_upnp.friendly_name = "Test Storybutton"
        assert button.name() == "Test Storybutton"