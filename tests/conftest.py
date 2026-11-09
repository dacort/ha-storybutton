"""Shared fixtures for the Storybutton test suite."""

import pytest
from custom_components.storybutton.storybutton import DeviceDescription


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every HA test."""
    yield


@pytest.fixture
def device_description() -> DeviceDescription:
    """A DeviceDescription matching the live device at 192.168.7.48."""
    return DeviceDescription(
        udn="uuid:50b25025-9478-8092-a31c-00112238d9ea",
        friendly_name="SB-100-371C",
        manufacturer="Storybutton",
        model="SB-100",
        sw_version="Internet Radio 20250103.1801",
        serial="5025-9478-8092-a31c-0011-2238-d9ea-af4d",
    )
