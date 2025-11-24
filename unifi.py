import requests
import urllib3
import time
import threading
import json
import logging
from flask import Flask, request
from config import CONFIG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("UniFi")

class UnifiClient:
    def __init__(self):
        self.host = CONFIG["UNIFI_HOST"]
        self.api_key = CONFIG["API_KEY"]
        self.quality = CONFIG["STREAM_QUALITY"]
        
        self.base_url = f"https://{self.host}"
        self.headers = {
            "X-API-KEY": self.api_key,
            "Accept": "application/json",
        }
        
        # Motion state: {camera_id: last_motion_ts}
        self._motion_state = {}
        self._lock = threading.Lock()
        
        # Camera name to Camera ID mapping: {camera_name: camera_id}
        self._name_to_camera = {}
        
        # Flask App for Webhooks
        self.app = Flask(__name__)
        
        @self.app.route("/motion", methods=["POST"])
        def webhook():
            data = request.json
            if data:
                logger.debug(f"Webhook received: {json.dumps(data, indent=4)}")
                self._handle_webhook(data)
            return "OK", 200

    def get_cameras(self):
        """Fetch all cameras from the UniFi Protect API."""
        endpoint = f"{self.base_url}/proxy/protect/integration/v1/cameras"
        
        try:
            logger.info(f"Fetching cameras from {endpoint}...")
            resp = requests.get(endpoint, headers=self.headers, verify=False, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            cameras = data if isinstance(data, list) else (data.get("cameras", []) if isinstance(data, dict) else [])
            # Build name-to-camera mapping
            self._build_name_mapping(cameras)
            
            return cameras
        except Exception as e:
            logger.error(f"Error fetching cameras: {e}")
            return []

    def _build_name_mapping(self, cameras):
        """Build mapping from camera name to camera ID."""
        self._name_to_camera = {}
        for cam in cameras:
            cam_id = cam.get("id")
            cam_name = cam.get("name")
            if cam_name and cam_id:
                self._name_to_camera[cam_name] = cam_id
                logger.info(f"Mapped camera name '{cam_name}' -> camera ID {cam_id}")

    def _handle_webhook(self, data):
        """Handle webhook payload: extract camera name and update motion state."""
        try:
            alarm = data.get("alarm", {})
            camera_name = alarm.get("name")
            
            if camera_name:
                # Map camera name to camera ID
                cam_id = self._name_to_camera.get(camera_name)
                if cam_id:
                    logger.info(f"MOTION detected on '{camera_name}' -> camera ID {cam_id}")
                    with self._lock:
                        self._motion_state[cam_id] = time.time()
                else:
                    logger.warning(f"MOTION detected on '{camera_name}' but no camera mapping found")
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")

    def ensure_single_stream(self, camera_id):
        """Ensures only one RTSP stream of the configured quality exists for the camera."""
        endpoint = f"{self.base_url}/proxy/protect/integration/v1/cameras/{camera_id}/rtsps-stream"
        streams = {}
        try:
            resp = requests.get(endpoint, headers=self.headers, verify=False, timeout=10)
            if resp.status_code == 200:
                streams = resp.json()
            else:
                logger.warning(f"GET {endpoint} returned {resp.status_code}. Response: {resp.text[:100]}")
        except Exception as e:
            logger.error(f"Error getting streams for {camera_id}: {e}")
            return None

        existing_url = streams.get(self.quality)
        if existing_url:
            return existing_url
        
        if not streams:
            return self._create_stream(camera_id, self.quality)

        return None

    def _create_stream(self, camera_id, quality):
        """Create a new RTSP stream of the specified quality."""
        endpoint = f"{self.base_url}/proxy/protect/integration/v1/cameras/{camera_id}/rtsps-stream"
        payload = {"name": f"Auto-{quality}", "channel": 0, "quality": quality}
        try:
            resp = requests.post(endpoint, headers=self.headers, json=payload, verify=False, timeout=10)
            if resp.status_code in [200, 201]:
                data = resp.json()
                if quality in data: return data[quality]
                return data.get("rtspsAlias") 
            logger.warning(f"Create stream failed: {resp.status_code} {resp.text[:100]}")
        except Exception as e:
            logger.error(f"Error creating stream: {e}")
        return None

    def start_event_listener(self):
        """Starts the Flask server in a background thread."""
        t = threading.Thread(target=self._run_flask, daemon=True)
        t.start()

    def _run_flask(self):
        logger.info("Starting Webhook Server on port 5000...")
        try:
            self.app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"Flask server failed: {e}")

    def get_last_motion(self, camera_id):
        with self._lock:
            return self._motion_state.get(camera_id, 0)

    def stop(self):
        pass
