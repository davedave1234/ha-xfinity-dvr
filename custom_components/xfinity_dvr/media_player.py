import requests
import logging
import voluptuous as vol
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.components.media_player.const import (
    SUPPORT_PLAY,
    SUPPORT_PAUSE,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
    SUPPORT_PLAY_MEDIA
)

_LOGGER = logging.getLogger(__name__)

# Complete list of valid Xfinity vcodes
VALID_BUTTONS = [
    "GUIDE", "MENU", "PAGE_DOWN", "PAGE_UP", "CHANNEL_DOWN", "CHANNEL_UP", 
    "INFO", "UP", "DOWN", "LEFT", "RIGHT", "ENTER", "REWIND", "FAST_FORWARD", 
    "PLAY", "PREV", "EXIT", "RECORD", "COLOR_KEY_0", "COLOR_KEY_1", 
    "COLOR_KEY_2", "COLOR_KEY_3", "NUMBER_1", "NUMBER_2", "NUMBER_3", 
    "NUMBER_4", "NUMBER_5", "NUMBER_6", "NUMBER_7", "NUMBER_8", "NUMBER_9", "NUMBER_0"
]

SUPPORT_XFINITY = (
    SUPPORT_PLAY | SUPPORT_PAUSE | SUPPORT_NEXT_TRACK | 
    SUPPORT_PREVIOUS_TRACK | SUPPORT_TURN_ON | SUPPORT_TURN_OFF | SUPPORT_PLAY_MEDIA
)

SERVICE_SEND_BUTTON = "send_button_press"

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Xfinity DVR from a config entry and register custom services."""
    token = config_entry.data.get("arToken")
    entity = XfinityDVREntity(token)
    async_add_entities([entity])

    # Register the custom service to accept any vcode
    platform = async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_BUTTON,
        {
            vol.Required("button_code"): vol.In(VALID_BUTTONS),
        },
        "async_send_custom_button",
    )

class XfinityDVREntity(MediaPlayerEntity):
    """Representation of an Xfinity DVR."""

    def __init__(self, token):
        self._token = token
        self._state = "on"
        self._name = "Xfinity X1"
        self._api_url = "https://accrem.apps.cloud.comcast.net/api/v1/processKey"
        self._voice_url = "https://accrem.apps.cloud.comcast.net/api/v1/text"

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def supported_features(self):
        return SUPPORT_XFINITY

    def _send_key(self, key_code):
        """Send a standard button press to the API."""
        payload = {"arToken": self._token, "vcode": key_code}
        try:
            requests.post(self._api_url, json=payload, timeout=5)
        except Exception as e:
            _LOGGER.error(f"Error communicating with Xfinity API: {e}")

    async def async_send_custom_button(self, button_code):
        """Service call to send any specific remote button."""
        # Run the synchronous HTTP request in the executor to avoid blocking HA
        await self.hass.async_add_executor_job(self._send_key, button_code)

    def media_play(self):
        self._send_key("PLAY")

    def media_pause(self):
        self._send_key("PLAY") # PLAY toggles play/pause on X1

    def media_next_track(self):
        self._send_key("CHANNEL_UP")

    def media_previous_track(self):
        self._send_key("CHANNEL_DOWN")

    def turn_on(self):
        self._send_key("MENU") # X1 boxes don't have discrete power; menu wakes them

    def play_media(self, media_type, media_id, **kwargs):
        """Use the voice command endpoint for absolute actions."""
        payload = {"arToken": self._token, "cmd": f"Watch {media_id}"}
        try:
            requests.post(self._voice_url, json=payload, timeout=5)
        except Exception as e:
            _LOGGER.error(f"Error sending voice command: {e}")