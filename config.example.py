"""
Configuration template. Copy to config.py and fill in API_KEY and UNIFI_HOST.
The install script (install_pi.sh) can generate config.py interactively.
"""
CONFIG = {
    "API_KEY": "API_KEY_HERE",
    "UNIFI_HOST": "UNIFI_HOST_HERE",
    "STREAM_QUALITY": "low",
    "RETRY_SECONDS": 60,
    "TARGET_HEIGHT": 540,
    "VIDEOS_FOLDER": "videos",
    "BUTTONS_JSON": "buttons.json",
    "SCHEDULED_VIDEOS": [],
    "CONTROL_PANEL_PORT": 5000,
    "SECRET_KEY": "change-me-in-production",
}
