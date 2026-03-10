"""
Configuration template. Copy to config.py and fill in API_KEY and UNIFI_HOST.
The install script (install_pi.sh) can generate config.py interactively.
"""
CONFIG = {
    "API_KEY": "API_KEY_HERE",
    "UNIFI_HOST": "UNIFI_HOST_HERE",
    "STREAM_QUALITY": "low",  # Options: "high", "medium", "low"
    "RETRY_SECONDS": 60,
    "TARGET_HEIGHT": 540,  # Default height for placeholder images
    "VIDEOS_FOLDER": "videos",  # Folder for MP4 files (relative to project root)
    "BUTTONS_JSON": "buttons.json",  # Path relative to project root
    "SCHEDULED_VIDEOS": [  # List of time -> video mappings (24h HH:MM)
        {"time": "23:11", "file": "LEBRON.mp4"},
        {"time": "11:11", "file": "LEBRON.mp4"}
    ],
    "CONTROL_PANEL_PORT": 5000,  # Web control panel port (single webserver)
    "CONTROL_PANEL_BASE_PATH": "/",  # Base URL path for control panel (default "/")
}
