import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .const import DEFAULT_NAME, DOMAIN


class StorybuttonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Storybutton config flow."""

    VERSION = 1
    MINOR_VERSION = 0

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            # You can add additional validation here if desired.
            # For example, check if the host is reachable.

            # Use the provided name or fallback to default.
            title = user_input.get(CONF_NAME) or DEFAULT_NAME

            return self.async_create_entry(title=title, data=user_input)

        # Define the data schema for user input.
        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
