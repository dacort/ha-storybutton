"""Config + discovery flow tests (run under pytest-homeassistant-custom-component)."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.storybutton.const import DOMAIN
from custom_components.storybutton.storybutton import DeviceDescription

_FETCH = "custom_components.storybutton.config_flow.async_fetch_device_description"
_SETUP = "custom_components.storybutton.async_setup_entry"
_HOST = "192.168.7.48"
# Real Espressif network MAC reported by DHCP (distinct from the UDN's placeholder).
_MAC_RAW = "348518ae371c"
_MAC = "34:85:18:ae:37:1c"


def _dhcp_info(ip: str = _HOST) -> DhcpServiceInfo:
    return DhcpServiceInfo(ip=ip, hostname="sb-100-371c", macaddress=_MAC_RAW)


async def test_user_flow_creates_entry(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """A successful user flow fetches device.xml and keys the entry on the UDN."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch(_FETCH, return_value=device_description),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: _HOST, CONF_NAME: "Amelia's Storybutton"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == device_description.udn
    assert result["data"][CONF_HOST] == _HOST
    assert result["data"][CONF_NAME] == "Amelia's Storybutton"


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A failed device.xml fetch re-shows the form with a cannot_connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(_FETCH, side_effect=OSError("boom")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.9"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_updates_host(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """Re-adding a known device aborts but re-points the stored host."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_description.udn,
        data={CONF_HOST: "192.168.7.99", CONF_NAME: "Amelia"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(_FETCH, return_value=device_description):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: _HOST}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == _HOST


async def test_dhcp_discovery_confirm_creates_entry(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """DHCP discovery of a new device shows a confirm form, then creates it."""
    with (
        patch(_FETCH, return_value=device_description),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == device_description.udn
    assert result["data"][CONF_HOST] == _HOST
    # The real network MAC from DHCP is captured for the device registry.
    assert result["data"][CONF_MAC] == _MAC


async def test_dhcp_self_heals_existing_host(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """A known device reappearing at a new IP updates the stored host silently."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_description.udn,
        data={CONF_HOST: "192.168.7.99", CONF_NAME: "Amelia"},
    )
    entry.add_to_hass(hass)

    with patch(_FETCH, return_value=device_description):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(_HOST),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == _HOST
    assert entry.data[CONF_MAC] == _MAC


async def test_dhcp_non_storybutton_aborts(hass: HomeAssistant) -> None:
    """A DHCP hit that isn't a reachable Storybutton aborts quietly."""
    with patch(_FETCH, side_effect=OSError("not a storybutton")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info("192.168.7.50"),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reconfigure_updates_host(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """Reconfigure validates the new host and re-points the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_description.udn,
        data={CONF_HOST: "192.168.7.99", CONF_NAME: "Amelia"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    with (
        patch(_FETCH, return_value=device_description),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: _HOST}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == _HOST


async def test_reconfigure_wrong_device_aborts(
    hass: HomeAssistant, device_description: DeviceDescription
) -> None:
    """Reconfiguring to a *different* physical device is rejected."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_description.udn,
        data={CONF_HOST: "192.168.7.99", CONF_NAME: "Amelia"},
    )
    entry.add_to_hass(hass)

    other = DeviceDescription(
        udn="uuid:ffffffff-ffff-ffff-ffff-ffffffffffff",
        friendly_name="Someone else",
    )
    result = await entry.start_reconfigure_flow(hass)
    with patch(_FETCH, return_value=other):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.7.77"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    # Original host is left untouched.
    assert entry.data[CONF_HOST] == "192.168.7.99"
