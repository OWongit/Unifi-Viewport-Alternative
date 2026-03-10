import os
from queue import Queue

from gui import App
import helpers
from unifi import UnifiClient
from control_panel import start_control_panel
from config import CONFIG

if __name__ == "__main__":
    try:
        helpers.log("Starting Dual Cam Viewer (Dynamic)...")
        
        client = UnifiClient()
        
        cameras = client.get_cameras()
        if not cameras:
            helpers.log("No cameras found! Exiting...")
            exit(1)
            
        # Prepare Streams
        active_streams = []
        for cam in cameras:
            name = cam.get("name", "Unknown")
            cam_id = cam.get("id")
            
            helpers.log(f"Processing camera: {name} ({cam_id})")
            
            # Ensure RTSP stream exists and get URL
            rtsp_url = client.ensure_single_stream(cam_id)
            
            if rtsp_url:
                active_streams.append({
                    "name": name,
                    "id": cam_id,
                    "url": rtsp_url
                })
            else:
                helpers.log(f"Could not get RTSP URL for {name}")

        if not active_streams:
            helpers.log("No active RTSP streams available. Exiting...")
            exit(1)

        # Create videos folder if needed
        videos_folder = CONFIG.get("VIDEOS_FOLDER", "videos")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        videos_path = os.path.join(base_dir, videos_folder)
        os.makedirs(videos_path, exist_ok=True)

        # Playback queue and control panel
        playback_queue = Queue()
        start_control_panel(playback_queue, len(active_streams))

        # Start GUI
        app = App(active_streams, client, playback_queue=playback_queue)
        app.start()
        
        # Cleanup on exit
        client.stop()

    except Exception as e:
        helpers.log(f"Fatal Error: {e}")
        raise
