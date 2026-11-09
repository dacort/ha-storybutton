"""Config flow for the Storybutton integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import DEFAULT_NAME, DOMAIN
from .storybutton import DeviceDescription, async_fetch_device_description

_LOGGER = logging.getLogger(__name__)


class StorybuttonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Storybutton config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered_host: str | None = None
        self._discovered_name: str = DEFAULT_NAME
        self._discovered_mac: str | None = None

    async def _async_describe(self, host: str) -> DeviceDescription:
        """Fetch and parse device.xml for ``host`` using HA's shared session."""
        session = async_get_clientsession(self.hass)
        return await async_fetch_device_description(session, host)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                desc = await self._async_describe(host)
            except Exception:  # noqa: BLE001 - device.xml fetch/parse can fail many ways
                _LOGGER.debug("Could not reach Storybutton at %s", host, exc_info=True)
                errors["base"] = "cannot_connect"
            else:
                # The UDN is the stable identity that survives IP changes.
                await self.async_set_unique_id(desc.udn)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                title = user_input.get(CONF_NAME) or desc.friendly_name or DEFAULT_NAME
                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host, CONF_NAME: title},
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle a device discovered via DHCP.

        This is what makes the integration self-healing: the device doesn't
        broadcast SSDP/mDNS, but it does take DHCP leases. When it appears at a
        new IP, HA matches it by MAC and fires this step; we confirm identity by
        UDN and update the stored host in place.
        """
        host = discovery_info.ip
        mac = format_mac(discovery_info.macaddress)
        try:
            desc = await self._async_describe(host)
        except Exception:  # noqa: BLE001 - not reachable / not actually a Storybutton
            _LOGGER.debug(
                "DHCP-discovered host %s is not a reachable Storybutton",
                host,
                exc_info=True,
            )
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(desc.udn)
        # If already configured, this updates the host/MAC and reloads (self-heal).
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_MAC: mac})

        self._discovered_host = host
        self._discovered_mac = mac
        self._discovered_name = desc.friendly_name or DEFAULT_NAME
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm adding a newly discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name,
                data={
                    CONF_HOST: self._discovered_host,
                    CONF_NAME: self._discovered_name,
                    CONF_MAC: self._discovered_mac,
                },
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._discovered_name},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Re-point an existing entry at a new host (the original 'edit IP' ask).

        Also backfills the UDN unique_id for legacy entries that predate it, so
        DHCP discovery can self-heal future moves.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                desc = await self._async_describe(host)
            except Exception:  # noqa: BLE001 - device.xml fetch/parse can fail many ways
                _LOGGER.debug("Could not reach Storybutton at %s", host, exc_info=True)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(desc.udn)
                # Guard against re-pointing an entry at a *different* device.
                # Legacy entries (unique_id is None) are exempt so they can be
                # backfilled with the now-known UDN.
                if entry.unique_id is not None:
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=desc.udn,
                    data_updates={CONF_HOST: host},
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=data_schema, errors=errors
        )
