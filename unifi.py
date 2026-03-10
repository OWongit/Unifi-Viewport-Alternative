import requests
import urllib3
import logging
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

    def get_cameras(self):
        """Fetch all cameras from the UniFi Protect API."""
        endpoint = f"{self.base_url}/proxy/protect/integration/v1/cameras"
        
        try:
            logger.info(f"Fetching cameras from {endpoint}...")
            resp = requests.get(endpoint, headers=self.headers, verify=False, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            cameras = data if isinstance(data, list) else (data.get("cameras", []) if isinstance(data, dict) else [])
            return cameras
        except Exception as e:
            logger.error(f"Error fetching cameras: {e}")
            return []

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

    def stop(self):
        pass
