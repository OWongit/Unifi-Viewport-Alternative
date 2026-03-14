CONFIG = {
    "API_KEY": "m52OoqTx1NICTmsjN-h7JvE-eFDqc3zY",
    "UNIFI_HOST": "192.168.1.1",
    "STREAM_QUALITY": "low",  # Options: "high", "medium", "low"
    "RETRY_SECONDS": 60,
    "TARGET_HEIGHT": 540,  # Default height for placeholder images
    "VIDEOS_FOLDER": "videos",  # Folder for MP4 files (relative to project root)
    "BUTTONS_JSON": "buttons.json",  # Path relative to project root
    "SCHEDULED_VIDEOS": [  # List of time -> video mappings (24h HH:MM)
        # Optional: "stream" (0-based camera index) or "streams" (list, random among them)
        {"time": "23:11", "file": "LEBRON.mp4", "stream": ["back cam", "front cam"]},
        {"time": "11:11", "file": "LEBRON.mp4", "streams": ["back cam", "front cam"]},
        {"time": "14:38", "file": "Add_Bigfoot_to_Webcam_Capture.mp4", "streams": "front cam"},
    ],
    "CONTROL_PANEL_PORT": 5000,
}
