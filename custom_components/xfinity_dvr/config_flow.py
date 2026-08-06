import asyncio
import logging
import uuid
import requests
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)
DOMAIN = "xfinity_dvr"

class XfinityDVRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xfinity DVR."""
    
    VERSION = 1

    def __init__(self):
        # Generate a version 4 UUID required by Comcast
        self._uuid = str(uuid.uuid4())
        self._temp_auth_token = None
        self._pairing_code = None
        self._ar_token = None
        self._poll_task = None

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: Initiate the Easy Pair process."""
        if user_input is not None:
            url = "https://accrem.apps.cloud.comcast.net/api/v1/pairing/start"
            payload = {"partner": "comcast", "clientDeviceId": self._uuid}
            
            try:
                # Use executor to avoid blocking HA's async event loop
                response = await self.hass.async_add_executor_job(
                    lambda: requests.post(url, json=payload, timeout=10).json()
                )
                self._temp_auth_token = response.get("authorizationToken")
                self._pairing_code = response.get("pairingCode")
                
                # Move to the progress step to wait for user input on the TV
                return await self.async_step_pairing_wait()

            except Exception as e:
                _LOGGER.error(f"Failed to start pairing: {e}")
                return self.async_show_form(step_id="user", errors={"base": "cannot_connect"})

        # Show an initial form with a simple submit button to begin
        return self.async_show_form(step_id="user")

    async def async_step_pairing_wait(self, user_input=None) -> FlowResult:
        """Step 2: Show the code and start the background polling task."""
        
        # Start the background task to poll the Comcast confirm endpoint
        if not self._poll_task:
            self._poll_task = self.hass.async_create_task(self._poll_comcast_api())

        # Show a progress dialog on the UI with the pairing code
        return self.async_show_progress(
            step_id="pairing_complete",
            progress_action="wait_for_pairing",
            description_placeholders={"pairing_code": self._pairing_code},
            progress_task=self._poll_task,
        )

    async def async_step_pairing_complete(self, user_input=None) -> FlowResult:
        """Step 3: Route the flow based on polling success or failure."""
        return self.async_show_progress_done(next_step_id="create_entry")

    async def async_step_create_entry(self, user_input=None) -> FlowResult:
        """Step 4: Create the final entry or show a failure message."""
        if not self._ar_token:
             return self.async_show_form(step_id="user", errors={"base": "pairing_failed"})
             
        # Save the permanent access token and UUID to the config entry
        return self.async_create_entry(
            title="Xfinity X1", 
            data={
                "arToken": self._ar_token, 
                "clientDeviceId": self._uuid
            }
        )

    async def _poll_comcast_api(self):
        """Background task that pings the Comcast API until confirmed."""
        url = "https://accrem.apps.cloud.comcast.net/api/v1/pairing/confirm"
        payload = {"partner": "comcast", "clientDeviceId": self._uuid}
        headers = {"X-Authorization": self._temp_auth_token}

        # Poll every 5 seconds for roughly 2 minutes (24 attempts)
        for _ in range(24):  
            await asyncio.sleep(5)
            try:
                response = await self.hass.async_add_executor_job(
                    lambda: requests.post(url, json=payload, headers=headers, timeout=5).json()
                )
                
                # Check if the user entered the code on their TV
                if response.get("status") == "CONFIRMED":
                    self._ar_token = response.get("accessRequestToken") 
                    
                    # Trigger the flow manager to move to the next step
                    self.hass.async_create_task(
                        self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
                    )
                    return True
                    
            except Exception as e:
                _LOGGER.debug(f"Polling failed this attempt: {e}")

        # If it times out, trigger the flow manager to advance (it will fail in Step 4)
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )
        return False