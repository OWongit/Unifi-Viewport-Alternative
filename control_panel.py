"""
Flask control panel for triggering video playback on stream windows.
Serves a web UI with buttons per MP4 file and runs the scheduled video scheduler.
"""
import json
import os
import random
import threading
import time
import logging
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
from config import CONFIG

logger = logging.getLogger("ControlPanel")

# Will be set by start_control_panel()
_playback_queue = None
_num_streams = 1


def _get_buttons_json_path():
    """Return absolute path to the buttons JSON file (path from CONFIG)."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = CONFIG.get("BUTTONS_JSON", "buttons.json")
    return os.path.join(base, path)


def _load_buttons():
    """Load buttons from JSON. Returns empty list if missing or invalid."""
    path = _get_buttons_json_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [b for b in data if isinstance(b, dict) and "file" in b and "name" in b]
    except (json.JSONDecodeError, OSError):
        return []


def _save_buttons(buttons):
    """Save buttons to JSON."""
    path = _get_buttons_json_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(buttons, f, indent=2)


def _get_videos_folder():
    """Return absolute path to videos folder."""
    base = os.path.dirname(os.path.abspath(__file__))
    folder = CONFIG.get("VIDEOS_FOLDER", "videos")
    return os.path.join(base, folder)


def _resolve_video_path(filename: str):
    """
    Resolve filename to absolute path. Returns None if invalid (path traversal, etc).
    """
    if not filename or ".." in filename or os.path.sep in filename or "/" in filename:
        return None
    folder = _get_videos_folder()
    path = os.path.join(folder, filename)
    if not os.path.isfile(path):
        return None
    # Ensure path is under folder (canonical)
    try:
        real_path = os.path.realpath(path)
        real_folder = os.path.realpath(folder)
        if not real_path.startswith(real_folder):
            return None
    except OSError:
        return None
    return path


def _get_static_folder():
    """Return path to static folder."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app(playback_queue, num_streams):
    """Create Flask app with routes. Used by start_control_panel."""
    global _playback_queue, _num_streams
    _playback_queue = playback_queue
    _num_streams = max(1, num_streams)

    app = Flask(__name__, static_folder=_get_static_folder())

    @app.route("/")
    def index():
        return send_from_directory(_get_static_folder(), "index.html")

    @app.route("/api/buttons", methods=["GET"])
    def get_buttons():
        return jsonify(_load_buttons())

    @app.route("/api/buttons", methods=["POST"])
    def add_button():
        file = request.files.get("file")
        name = (request.form.get("name") or "").strip()
        if not file or not name:
            return jsonify({"error": "File and name required"}), 400
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in (".mp4", ".mov"):
            return jsonify({"error": "Only .mp4 and .mov files allowed"}), 400
        filename = secure_filename(os.path.basename(file.filename))
        if not filename:
            return jsonify({"error": "Invalid filename"}), 400
        folder = _get_videos_folder()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            os.remove(path)
        try:
            file.save(path)
        except OSError as e:
            return jsonify({"error": str(e)}), 500
        buttons = _load_buttons()
        existing = next((i for i, b in enumerate(buttons) if b.get("file") == filename), None)
        if existing is not None:
            buttons[existing] = {"file": filename, "name": name}
        else:
            buttons.append({"file": filename, "name": name})
        _save_buttons(buttons)
        return jsonify({"ok": True})

    @app.route("/api/buttons/<int:index>", methods=["DELETE"])
    def delete_button(index):
        buttons = _load_buttons()
        if index < 0 or index >= len(buttons):
            return jsonify({"error": "Invalid index"}), 400
        entry = buttons.pop(index)
        filename = entry.get("file")
        if filename:
            path = _resolve_video_path(filename)
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                    logger.info(f"Deleted video file: {filename}")
                except OSError as e:
                    logger.warning(f"Could not delete video file {filename}: {e}")
        _save_buttons(buttons)
        return jsonify({"ok": True})

    @app.route("/api/buttons", methods=["PUT"])
    def put_buttons():
        data = request.get_json()
        if not data or "buttons" not in data:
            return jsonify({"error": "buttons array required"}), 400
        raw = data["buttons"]
        if not isinstance(raw, list):
            return jsonify({"error": "buttons must be array"}), 400
        buttons = []
        for b in raw:
            if isinstance(b, dict) and "file" in b and "name" in b:
                buttons.append({"file": str(b["file"]), "name": str(b["name"])})
        _save_buttons(buttons)
        return jsonify({"ok": True})

    @app.route("/play/<path:filename>", methods=["POST"])
    def play(filename):
        # Normalize: take only the basename to avoid path traversal
        filename = os.path.basename(filename)
        path = _resolve_video_path(filename)
        if not path:
            return jsonify({"ok": False, "error": "Invalid or missing video"}), 400

        stream_index = random.randint(0, _num_streams - 1)
        _playback_queue.put((path, stream_index))
        return jsonify({"ok": True, "stream": stream_index})

    return app


def _run_scheduler(playback_queue, num_streams):
    """Background thread: check SCHEDULED_VIDEOS every minute."""
    from datetime import datetime

    scheduled = CONFIG.get("SCHEDULED_VIDEOS", [])
    if not scheduled:
        return

    last_triggered = {}  # time_str -> timestamp
    folder = _get_videos_folder()

    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            for entry in scheduled:
                if not isinstance(entry, dict):
                    continue
                time_str = entry.get("time")
                file_name = entry.get("file")
                if not time_str or not file_name:
                    continue

                if current_time != time_str:
                    continue

                # Avoid firing multiple times in same minute
                last = last_triggered.get(time_str, 0)
                if now.timestamp() - last < 55:
                    continue

                path = os.path.join(folder, file_name)
                if not os.path.isfile(path):
                    logger.warning(f"Scheduled video not found: {path}")
                    continue

                stream_index = random.randint(0, num_streams - 1)
                playback_queue.put((path, stream_index))
                last_triggered[time_str] = now.timestamp()
                logger.info(f"Scheduled playback: {file_name} on stream {stream_index}")

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(60)  # Check every minute


def start_control_panel(playback_queue, num_streams):
    """Start Flask control panel and scheduler in background threads."""
    # Ensure buttons.json exists
    path = _get_buttons_json_path()
    if not os.path.isfile(path):
        _save_buttons([])

    port = CONFIG.get("CONTROL_PANEL_PORT", 5000)
    app = create_app(playback_queue, num_streams)

    def run_flask():
        logger.info(f"Starting Control Panel on port {port}...")
        try:
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"Control panel failed: {e}")

    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    # Start scheduler if SCHEDULED_VIDEOS is non-empty
    if CONFIG.get("SCHEDULED_VIDEOS"):
        st = threading.Thread(
            target=_run_scheduler,
            args=(playback_queue, num_streams),
            daemon=True
        )
        st.start()
        logger.info("Scheduled video scheduler started.")
