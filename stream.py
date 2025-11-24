import threading
import time
import cv2
import helpers
from config import CONFIG

# ========= CONFIG =========
RETRY_SECONDS = CONFIG.get("RETRY_SECONDS", 60)

class RTSPStream:
    """
    Opens RTSP with OpenCV, continuously reads the latest frame in a thread,
    and attempts reconnect on failure with RETRY_SECONDS backoff.
    """

    def __init__(self, url: str, name: str):
        self.url = url
        self.name = name
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.last_read_ts = 0.0
        self.status = "idle"

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def get_frame(self):
        with self._lock:
            return (None if self._frame is None else self._frame.copy(), self.status, self.last_read_ts)

    def _run(self):
        while not self._stop.is_set():
            cap = helpers.open_capture(self.url)
            if not cap.isOpened():
                self.status = "connecting..."
                helpers.log(f"{self.name}: Error: Could not open RTSP stream. Retrying in {RETRY_SECONDS} seconds...")
                cap.release()
                self._sleep_with_stop(RETRY_SECONDS)
                continue

            self.status = "LIVE"
            helpers.log(f"{self.name}: RTSP stream opened successfully.")

            while not self._stop.is_set():
                ret, frame = cap.read()
                if not ret or frame is None:
                    self.status = "reconnecting"
                    helpers.log(f"{self.name}: Error: Could not read frame. Retrying in {RETRY_SECONDS} seconds...")
                    break
                with self._lock:
                    self._frame = frame
                    self.last_read_ts = time.time()

            cap.release()
            self._sleep_with_stop(RETRY_SECONDS)

    def _sleep_with_stop(self, seconds: int):
        end = time.time() + seconds
        while not self._stop.is_set() and time.time() < end:
            time.sleep(0.2)
