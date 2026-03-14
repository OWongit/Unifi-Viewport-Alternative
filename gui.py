import math
import tkinter as tk
import cv2
import time
import logging
from queue import Empty
from PIL import Image, ImageTk
from datetime import datetime

import helpers
from config import CONFIG
from stream import RTSPStream
from video_player import MP4FrameSource

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GUI")

class App:
    def __init__(self, camera_configs, unifi_client=None, playback_queue=None):
        """
        camera_configs: list of dicts {name, id, url}
        unifi_client: optional, reserved for future use
        playback_queue: queue.Queue for (video_path, stream_index) requests
        """
        self.root = tk.Tk()
        self.root.title("Multi Cam Viewer")
        self.root.configure(bg="black")
        
        # Fullscreen / Kiosk mode
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", self.close)
        self.root.bind("q", self.close)
        
        self.camera_configs = camera_configs
        self.unifi_client = unifi_client
        self.playback_queue = playback_queue
        self.overlay_state = {}  # stream_index -> MP4FrameSource
        self.overlay_start_times = {}  # stream_index -> float (when overlay started)
        self.num_cams = len(camera_configs)
        
        # Calculate Grid Size (NxN approx)
        if self.num_cams == 1:
            self.rows = 1
            self.cols = 1
        elif self.num_cams == 2:
            self.rows = 1
            self.cols = 2
        else:
            self.cols = math.ceil(math.sqrt(self.num_cams))
            self.rows = math.ceil(self.num_cams / self.cols)

        # Configure Grid Weights
        for r in range(self.rows):
            self.root.grid_rowconfigure(r, weight=1, uniform="row")
        for c in range(self.cols):
            self.root.grid_columnconfigure(c, weight=1, uniform="col")

        # Initialize Widgets and Streams
        self.streams = []  # List of RTSPStream objects
        self.labels = []   # List of tk.Label widgets
        
        for i, config in enumerate(camera_configs):
            r = i // self.cols
            c = i % self.cols
            
            # Create Label
            lbl = tk.Label(self.root, bg="black")
            lbl.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)
            self.labels.append(lbl)
            
            # Create Stream
            stream = RTSPStream(config["url"], config["name"])
            stream.start()
            self.streams.append(stream)

        # Clock Overlay (Bottom Right)
        self.lbl_clock = tk.Label(
            self.root, 
            text="--:--", 
            font=("Helvetica", 24, "bold"), 
            bg="black", 
            fg="white"
        )
        self.lbl_clock.place(relx=0.992, rely=0.992, anchor="se")

        # Start Loops
        self.update_clock()
        self.update_video()

    def start(self):
        self.root.mainloop()

    def close(self, event=None):
        logger.info("Closing application...")
        for overlay in self.overlay_state.values():
            overlay.close()
        self.overlay_state.clear()
        self.overlay_start_times.clear()
        for s in self.streams:
            s.stop()
        self.root.destroy()
        
    def update_clock(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lbl_clock.config(text=now)
        self.root.after(1000, self.update_clock)

    def update_video(self):
        """
        Main video loop. Fetches frames, resizes, and updates labels.
        """
        if not self.labels: return

        # Process playback requests from control panel
        # Queue items: (path, allowed_stream_indices) - pick stream with earliest start time
        if self.playback_queue:
            try:
                while True:
                    path, allowed = self.playback_queue.get_nowait()
                    if not isinstance(allowed, (list, tuple)):
                        allowed = [allowed] if isinstance(allowed, int) else list(range(self.num_cams))
                    allowed = [s for s in allowed if isinstance(s, int) and 0 <= s < len(self.streams)]
                    if not allowed:
                        allowed = list(range(len(self.streams)))
                    # Prefer empty slots; among full slots, pick the one with earliest start time
                    now = time.time()
                    best_stream = None
                    best_start = None  # None = empty (prefer), else float
                    for s in allowed:
                        if s not in self.overlay_state:
                            best_stream = s
                            best_start = None
                            break
                        st = self.overlay_start_times.get(s)
                        if best_start is None or (st is not None and st < best_start):
                            best_stream = s
                            best_start = st
                    if best_stream is not None:
                        evicted = best_stream in self.overlay_state
                        if evicted:
                            self.overlay_state[best_stream].close()
                            del self.overlay_state[best_stream]
                            del self.overlay_start_times[best_stream]
                        self.overlay_state[best_stream] = MP4FrameSource(path)
                        self.overlay_start_times[best_stream] = now
                        logger.info(f"Playing {path} on stream {best_stream}" + (" (evicted earliest)" if evicted else ""))
            except Empty:
                pass  # Queue empty

        for i, stream in enumerate(self.streams):
            label_widget = self.labels[i]
            config = self.camera_configs[i]
            cam_id = config["id"]
            name = config["name"]
            
            w = label_widget.winfo_width()
            h = label_widget.winfo_height()
            
            # Startup sanity check
            if w < 10: w = self.root.winfo_screenwidth() // self.cols
            if h < 10: h = self.root.winfo_screenheight() // self.rows

            self._update_single_view(i, label_widget, stream, w, h, name, cam_id)

        # Target ~30 FPS
        self.root.after(24, self.update_video)

    def _update_single_view(self, stream_index, label_widget, stream, width, height, name, cam_id):
        # Check for MP4 overlay on this stream
        if stream_index in self.overlay_state:
            overlay = self.overlay_state[stream_index]
            frame, status, ts = overlay.get_frame()
            if frame is None:
                overlay.close()
                del self.overlay_state[stream_index]
                self.overlay_start_times.pop(stream_index, None)
                frame, status, ts = stream.get_frame()
        else:
            frame, status, ts = stream.get_frame()

        stale = False
        if frame is None:
            # Create placeholder if no frame yet
            frame = helpers.make_placeholder(f"{name}: {status}", width, height)
        else:
            # Check for staleness
            now = time.time()
            stale = (now - ts) > 2.0 if ts > 0 else True
            
            # Letterbox to fit the label area
            frame = helpers.letterbox_to_size(frame, width, height)

        # Convert to Tkinter format
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)

        # Annotate with Text
        img = helpers.draw_overlay(img, name, status, stale, motion_active=False, motion_alpha=1.0)
        
        imgtk = ImageTk.PhotoImage(image=img)

        # Update label
        label_widget.configure(image=imgtk)
        label_widget.image = imgtk  # Keep reference!
