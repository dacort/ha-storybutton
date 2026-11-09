from typing import Tuple
from unittest.mock import Mock, create_autospec

import pytest
import requests
import upnpclient

from custom_components.storybutton.storybutton import (
    DeviceDescription,
    State,
    Storybutton,
    StorybuttonConfig,
)


# Verbatim device.xml from the live device (192.168.7.48). Kept exact so the
# parser is regression-tested against the device's real format: UDN before
# friendlyName, a namespaced dlna:X_DLNADOC element, and a serviceList.
SAMPLE_DEVICE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
<specVersion>
<major>1</major>
<minor>0</minor>
</specVersion>
<device>
<UDN>uuid:50b25025-9478-8092-a31c-00112238d9ea</UDN>
<friendlyName>SB-100-371C</friendlyName>
<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
<dlna:X_DLNADOC xmlns:dlna="urn:schemas-dlna-org:device-1-0">DMR-1.50</dlna:X_DLNADOC>
<manufacturer>Storybutton</manufacturer>
<manufacturerURL>https://storybutton.com/</manufacturerURL>
<modelName>SB-100</modelName>
<modelNumber>PR-100v2</modelNumber>
<modelURL>http://192.168.7.48</modelURL>
<modelDescription>Internet Radio 20250103.1801</modelDescription>
<serialNumber>5025-9478-8092-a31c-0011-2238-d9ea-af4d</serialNumber>
<presentationURL>http://192.168.7.48</presentationURL>
<UPC>PR-100v2</UPC>
<serviceList>
<service>
<serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
<serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
<SCPDURL>/upnp/rc.xml</SCPDURL>
<controlURL>/upnp/rc</controlURL>
<eventSubURL>/upnp/re</eventSubURL>
</service>
</serviceList>
</device>
</root>
"""


class TestDeviceDescription:
    def test_from_xml_parses_all_fields(self):
        desc = DeviceDescription.from_xml(SAMPLE_DEVICE_XML)

        assert desc.udn == "uuid:50b25025-9478-8092-a31c-00112238d9ea"
        assert desc.friendly_name == "SB-100-371C"
        assert desc.manufacturer == "Storybutton"
        assert desc.model == "SB-100"
        assert desc.sw_version == "Internet Radio 20250103.1801"
        assert desc.serial == "5025-9478-8092-a31c-0011-2238-d9ea-af4d"

    def test_from_xml_missing_optional_fields(self):
        minimal = (
            '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
            "<friendlyName>Bare</friendlyName>"
            "<UDN>uuid:50b25025-9478-8092-a31c-00112238d9ea</UDN>"
            "</device></root>"
        )
        desc = DeviceDescription.from_xml(minimal)

        assert desc.friendly_name == "Bare"
        assert desc.udn == "uuid:50b25025-9478-8092-a31c-00112238d9ea"
        assert desc.manufacturer is None
        assert desc.model is None
        assert desc.sw_version is None
        assert desc.serial is None

    def test_from_xml_prefers_root_device_over_embedded(self):
        nested = (
            '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
            "<friendlyName>Root Device</friendlyName>"
            "<UDN>uuid:50b25025-9478-8092-a31c-00112238d9ea</UDN>"
            "<deviceList><device>"
            "<friendlyName>Embedded</friendlyName>"
            "<UDN>uuid:ffffffff-ffff-ffff-ffff-ffffffffffff</UDN>"
            "</device></deviceList>"
            "</device></root>"
        )
        desc = DeviceDescription.from_xml(nested)

        assert desc.friendly_name == "Root Device"
        assert desc.udn == "uuid:50b25025-9478-8092-a31c-00112238d9ea"


@pytest.fixture
def mock_upnp() -> Mock:
    """Create a mock UPnP device with all required attributes and methods."""
    mock = create_autospec(upnpclient.Device)

    # Set up RenderingControl service
    mock.RenderingControl = Mock()
    mock.RenderingControl.GetVolume.return_value = {"CurrentVolume": 50}

    # Set up AVTransport service
    mock.AVTransport = Mock()
    mock.AVTransport.GetTransportInfo.return_value = {
        "CurrentTransportState": "PLAYING"
    }

    # Set friendly name
    mock.friendly_name = "Test Device"

    return mock


@pytest.fixture
def mock_session() -> Mock:
    """Create a mock requests.sessions.Session ."""
    return create_autospec(requests.sessions.Session)


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
        host="test-host", http_client=mock_session, upnp_factory=lambda _: mock_upnp
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
        mock_session.get.assert_called_once_with("http://test-host", timeout=3)

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

    @pytest.mark.parametrize(
        "transport_state,expected_state",
        [
            ("playing", State.PLAYING),
            ("paused", State.PAUSED),
            (None, State.UNKNOWN),
        ],
    )
    def test_status_various_states(self, storybutton, transport_state, expected_state):
        """Test status for different transport states."""
        button, mock_upnp, mock_session = storybutton

        # Ensure device appears online
        mock_session.get.return_value = Mock(status_code=200)

        # Configure transport state
        mock_session.get.return_value.json.return_value = {
            "chStatus": f"Play state: {transport_state}",
            "result": "success",
        }

        assert button.status() == expected_state

    def test_volume_controls(self, storybutton):
        """Test volume control functions."""
        button, mock_upnp, _ = storybutton

        # Test get_volume
        mock_upnp.RenderingControl.GetVolume.return_value = {"CurrentVolume": 50}
        assert button.get_volume() == 50

        # Test volume_up
        new_volume = button.volume_up()
        assert new_volume == 51
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0, Channel="Master", DesiredVolume=51
        )

        # Test volume_down
        mock_upnp.RenderingControl.GetVolume.return_value = {"CurrentVolume": 51}
        new_volume = button.volume_down()
        assert new_volume == 50
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0, Channel="Master", DesiredVolume=50
        )

    def test_volume_limits(self, storybutton):
        """Test volume limits (0-100)."""
        button, mock_upnp, _ = storybutton

        # Test upper limit
        mock_upnp.RenderingControl.GetVolume.return_value = {"CurrentVolume": 100}
        assert button.volume_up() == 100
        mock_upnp.RenderingControl.SetVolume.assert_not_called()

        # Test lower limit
        mock_upnp.RenderingControl.GetVolume.return_value = {"CurrentVolume": 0}
        assert button.volume_down() == 0
        mock_upnp.RenderingControl.SetVolume.assert_not_called()

    def test_set_volume_limits(self, storybutton):
        """Test set_volume respects limits."""
        button, mock_upnp, _ = storybutton

        # Test above max
        button.set_volume(150)
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0, Channel="Master", DesiredVolume=100
        )

        # Test below min
        button.set_volume(-10)
        mock_upnp.RenderingControl.SetVolume.assert_called_with(
            InstanceID=0, Channel="Master", DesiredVolume=0
        )

    def test_playback_controls(self, storybutton):
        """Test playback control functions."""
        button, mock_upnp, _ = storybutton

        button.play()
        mock_upnp.AVTransport.Play.assert_called_with(InstanceID=0, Speed="1")

        button.pause()
        mock_upnp.AVTransport.Pause.assert_called_with(InstanceID=0)

    def test_mute_controls(self, storybutton):
        """Test mute control functions."""
        button, mock_upnp, _ = storybutton

        button.mute()
        mock_upnp.RenderingControl.SetMute.assert_called_with(
            InstanceID=0, Channel="Master", DesiredMute="1"
        )

        button.unmute()
        mock_upnp.RenderingControl.SetMute.assert_called_with(
            InstanceID=0, Channel="Master", DesiredMute="0"
        )

    def test_title(self, storybutton):
        """Test title retrieval."""
        button, _, mock_session = storybutton

        # Test successful title retrieval
        mock_session.get.return_value.json.return_value = {"name": "Test Track"}
        assert button.title() == "Test Track"
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
