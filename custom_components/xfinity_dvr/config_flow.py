import asyncio
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
        self._poll_task = None

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: Initiate the Easy Pair process."""
        errors = {}
        
        if user_input is not None:
            # Swap requests for aiohttp (HA's native async web client)
            session = async_get_clientsession(self.hass)
            url = "https://accrem.apps.cloud.comcast.net/api/v1/pairing/start"
            payload = {"partner": "comcast", "clientDeviceId": self._uuid}
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
            
            try:
                async with session.post(url, json=payload, headers=headers, timeout=10) as response:
                    text = await response.text()
                    _LOGGER.warning(f"Xfinity Start Response: {response.status} - {text}")
                    
                    if response.status == 200:
                        data = await response.json()
                        self._temp_auth_token = data.get("authorizationToken")
                        self._pairing_code = str(data.get("pairingCode"))
                        
                        return await self.async_step_pairing_wait()
                    else:
                        errors["base"] = "cannot_connect"
                        
            except Exception as e:
                _LOGGER.error(f"Failed to start pairing: {e}")
                errors["base"] = "cannot_connect"

        # Explicitly pass an empty schema so the frontend knows how to render
        return self.async_show_form(
            step_id="user", 
            data_schema=vol.Schema({}),
            errors=errors
        )

    async def async_step_pairing_wait(self, user_input=None) -> FlowResult:
        """Step 2: Show the code and start the background polling task."""
        
        if not self._poll_task:
            self._poll_task = self.hass.async_create_task(self._poll_comcast_api())

        # If the background task finishes, route directly to the final entry step
        if self._poll_task.done():
            return self.async_show_progress_done(next_step_id="create_entry")

        # The step_id MUST match the current step ("pairing_wait")
        return self.async_show_progress(
            step_id="pairing_wait",
            progress_action="wait_for_pairing",
            description_placeholders={"pairing_code": self._pairing_code},
            progress_task=self._poll_task,
        )

    async def async_step_create_entry(self, user_input=None) -> FlowResult:
        """Step 3: Create the final entry or show a failure message."""
        if not self._ar_token:
             return self.async_show_form(step_id="user", errors={"base": "pairing_failed"})
             
        return self.async_create_entry(
            title="Xfinity X1", 
            data={
                "arToken": self._ar_token, 
                "clientDeviceId": self._uuid
            }
        )

    async def _poll_comcast_api(self):
        """Background task that pings the Comcast API until confirmed."""
        session = async_get_clientsession(self.hass)
        url = "https://accrem.apps.cloud.comcast.net/api/v1/pairing/confirm"
        payload = {"partner": "comcast", "clientDeviceId": self._uuid}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-Authorization": self._temp_auth_token
        }

        for _ in range(24):  
            await asyncio.sleep(5)
            try:
                async with session.post(url, json=payload, headers=headers, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "CONFIRMED":
                            self._ar_token = data.get("accessRequestToken") 
                            
                            # Trigger the flow manager to re-run the wait step
                            self.hass.async_create_task(
                                self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
                            )
                            return True
            except Exception as e:
                _LOGGER.debug(f"Polling failed this attempt: {e}")

        # Trigger advance on timeout/failure
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )
        return False
