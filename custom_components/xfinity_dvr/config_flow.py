import logging
import uuid
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
DOMAIN = "xfinity_dvr"

class XfinityDVRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xfinity DVR."""
    
    VERSION = 1

    def __init__(self):
        self._uuid = str(uuid.uuid4())
        self._temp_auth_token = None
        self._pairing_code = None
        self._ar_token = None

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: Initiate the Easy Pair process."""
        errors = {}
        
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            url = "https://accrem.apps.cloud.comcast.net/api/v1/pairing/start"
            payload = {"partner": "comcast", "clientDeviceId": self._uuid}
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
            
            try:
                async with session.post(url, json=payload, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._temp_auth_token = data.get("authorizationToken")
                        self._pairing_code = str(data.get("pairingCode"))
                        
                        # Move directly to Step 2 to display the code card
                        return await self.async_step_pairing_code()
                    else:
                        errors["base"] = "cannot_connect"
                        
            except Exception as e:
                _LOGGER.error(f"Failed to start pairing: {e}")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", 
            data_schema=vol.Schema({}),
            errors=errors
        )

    async def async_step_pairing_code(self, user_input=None) -> FlowResult:
        """Step 2: Display the pairing code and confirm when user clicks Submit."""
        errors = {}

        if user_input is not None:
            # User clicked Submit after entering the code on their TV
            session = async_get_clientsession(self.hass)
            url = "https://accrem.apps.cloud.comcast.net/api/v1/pairing/confirm"
            payload = {"partner": "comcast", "clientDeviceId": self._uuid}
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "X-Authorization": self._temp_auth_token
            }

            try:
                async with session.post(url, json=payload, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "CONFIRMED":
                            self._ar_token = data.get("accessRequestToken")
                            return self.async_create_entry(
                                title="Xfinity X1",
                                data={
                                    "arToken": self._ar_token,
                                    "clientDeviceId": self._uuid
                                }
                            )
                        else:
                            errors["base"] = "pairing_failed"
                    else:
                        errors["base"] = "pairing_failed"
            except Exception as e:
                _LOGGER.error(f"Confirmation request failed: {e}")
                errors["base"] = "cannot_connect"

        # Show the standard form with the code embedded in the description
        return self.async_show_form(
            step_id="pairing_code",
            data_schema=vol.Schema({}),
            description_placeholders={"pairing_code": self._pairing_code},
            errors=errors
        )
