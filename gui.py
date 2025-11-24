import tkinter as tk
import cv2
import time
import math
import logging
from PIL import Image, ImageTk
from datetime import datetime

import helpers
from config import CONFIG
from stream import RTSPStream

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GUI")

class App:
    def __init__(self, camera_configs, unifi_client=None):
        """
        camera_configs: list of dicts {name, id, url}
        unifi_client: instance of UnifiClient to query motion state
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

            self._update_single_view(label_widget, stream, w, h, name, cam_id)

        # Target ~30 FPS
        self.root.after(33, self.update_video)

    def _update_single_view(self, label_widget, stream, width, height, name, cam_id):
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
        
        # Check Motion State (only if enabled in config)
        is_motion = False
        pulse = 1.0
        if CONFIG.get("ENABLE_MOTION_DETECTION", True) and self.unifi_client:
            last_motion = self.unifi_client.get_last_motion(cam_id)
            if time.time() - last_motion < 8.0: # buffer
                is_motion = True
                # Calculate Pulse Intensity if motion is active
                # Pulse effect: oscillate alpha between ~0.2 and 1.0
                # Speed factor: 8.0 (approx 1.25 Hz)
                pulse = (math.sin(time.time() * 8.0) + 1) / 2  # 0.0 to 1.0
                pulse = 0.2 + (pulse * 0.8) # 0.2 to 1.0 range

        # Annotate with Text and/or Motion Border
        img = helpers.draw_overlay(img, name, status, stale, motion_active=is_motion, motion_alpha=pulse)
        
        imgtk = ImageTk.PhotoImage(image=img)

        # Update label
        label_widget.configure(image=imgtk)
        label_widget.image = imgtk  # Keep reference!
