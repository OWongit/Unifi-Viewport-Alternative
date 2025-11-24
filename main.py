from gui import App
import helpers
from unifi import UnifiClient
import time

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

        # Webhook Server for Motion Events
        client.start_event_listener()

        # Start GUI
        app = App(active_streams, client)
        app.start()
        
        # Cleanup on exit
        client.stop()

    except Exception as e:
        helpers.log(f"Fatal Error: {e}")
        raise
