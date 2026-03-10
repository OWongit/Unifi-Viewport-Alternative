"""
MP4 video playback for overlay on stream windows.
Provides MP4FrameSource compatible with RTSPStream's get_frame() interface.
"""
import time
import helpers


def open_capture(path: str):
    """Open video capture for file path (MP4). Uses same backend as helpers."""
    return helpers.open_capture(path)


class MP4FrameSource:
    """
    Wraps cv2.VideoCapture for an MP4 file.
    Provides get_frame() compatible with RTSPStream: returns (frame, status, timestamp).
    Returns (None, "ended", ts) when video reaches end-of-file.
    """

    def __init__(self, path: str):
        self.path = path
        self._cap = open_capture(path)
        self._last_ts = 0.0
        self.status = "playing" if self._cap.isOpened() else "error"

    def get_frame(self):
        """Returns (frame, status, timestamp). Frame is None when ended or error."""
        if not self._cap or not self._cap.isOpened():
            return (None, "error", self._last_ts)

        ret, frame = self._cap.read()
        if not ret or frame is None:
            self.status = "ended"
            return (None, "ended", self._last_ts)

        self._last_ts = time.time()
        return (frame.copy(), self.status, self._last_ts)

    def close(self):
        """Release the video capture."""
        if self._cap:
            self._cap.release()
            self._cap = None

    def is_open(self):
        """Check if capture is still open."""
        return self._cap is not None and self._cap.isOpened()
