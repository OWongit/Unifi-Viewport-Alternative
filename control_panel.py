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
_stream_names = []  # Camera names for display, e.g. ["Front cam", "Back cam"]


def _get_buttons_json_path():
    """Return absolute path to the buttons JSON file (path from CONFIG)."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = CONFIG.get("BUTTONS_JSON", "buttons.json")
    return os.path.join(base, path)


def _parse_streams(raw: str):
    """Parse streams from form value. Returns list of valid indices or None (meaning all)."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw) if raw.strip().startswith("[") else [int(x.strip()) for x in raw.split(",") if x.strip()]
        if not parsed:
            return None
        valid = [s for s in parsed if isinstance(s, int) and 0 <= s < _num_streams]
        return sorted(set(valid)) if valid else None
    except (json.JSONDecodeError, ValueError):
        return None


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


def create_app(playback_queue, num_streams, stream_names=None):
    """Create Flask app with routes. Used by start_control_panel."""
    global _playback_queue, _num_streams, _stream_names
    _playback_queue = playback_queue
    _num_streams = max(1, num_streams)
    _stream_names = stream_names if stream_names and len(stream_names) == _num_streams else [
        f"Camera {i + 1}" for i in range(_num_streams)
    ]

    app = Flask(__name__, static_folder=_get_static_folder())

    def _get_images_folder():
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

    @app.route("/")
    def index():
        return send_from_directory(_get_static_folder(), "index.html")

    @app.route("/favicon.png")
    def favicon():
        return send_from_directory(_get_images_folder(), "favicon.png")

    @app.route("/api/streams", methods=["GET"])
    def get_streams():
        """Return stream count, indices, and camera names for selection."""
        return jsonify({
            "count": _num_streams,
            "streams": [{"index": i, "name": _stream_names[i]} for i in range(_num_streams)]
        })

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
        # Parse streams: JSON array or comma-separated indices
        streams_raw = request.form.get("streams", "")
        streams = _parse_streams(streams_raw)
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
        entry = {"file": filename, "name": name}
        if streams is not None:
            entry["streams"] = streams
        existing = next((i for i, b in enumerate(buttons) if b.get("file") == filename), None)
        if existing is not None:
            buttons[existing] = entry
        else:
            buttons.append(entry)
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
                entry = {"file": str(b["file"]), "name": str(b["name"])}
                if "streams" in b and isinstance(b["streams"], list):
                    valid = [s for s in b["streams"] if isinstance(s, int) and 0 <= s < _num_streams]
                    if valid:
                        entry["streams"] = sorted(set(valid))
                buttons.append(entry)
        _save_buttons(buttons)
        return jsonify({"ok": True})

    @app.route("/play/<path:filename>", methods=["POST"])
    def play(filename):
        # Normalize: take only the basename to avoid path traversal
        filename = os.path.basename(filename)
        path = _resolve_video_path(filename)
        if not path:
            return jsonify({"ok": False, "error": "Invalid or missing video"}), 400

        # Find button to get allowed streams; default to all if not set
        buttons = _load_buttons()
        allowed = list(range(_num_streams))
        for b in buttons:
            if b.get("file") == filename and b.get("streams"):
                valid = [s for s in b["streams"] if isinstance(s, int) and 0 <= s < _num_streams]
                if valid:
                    allowed = valid
                break
        stream_index = random.choice(allowed)
        _playback_queue.put((path, stream_index))
        return jsonify({"ok": True, "stream": stream_index})

    return app


def _run_scheduler(playback_queue, num_streams, stream_names=None):
    """Background thread: check SCHEDULED_VIDEOS every minute."""
    from datetime import datetime

    scheduled = CONFIG.get("SCHEDULED_VIDEOS", [])
    if not scheduled:
        return

    last_triggered = {}  # time_str -> timestamp
    folder = _get_videos_folder()
    names = stream_names if stream_names and len(stream_names) == num_streams else []

    def resolve_streams(entry):
        """Resolve stream/streams/camera/cameras to list of valid indices."""
        allowed = list(range(num_streams))
        if "stream" in entry and isinstance(entry["stream"], int) and 0 <= entry["stream"] < num_streams:
            return [entry["stream"]]
        if "streams" in entry and isinstance(entry["streams"], list):
            valid = [s for s in entry["streams"] if isinstance(s, int) and 0 <= s < num_streams]
            if valid:
                return valid
        if "camera" in entry and names:
            name = str(entry["camera"]).strip()
            for i, n in enumerate(names):
                if n and n.strip().lower() == name.lower():
                    return [i]
        if "cameras" in entry and names:
            name_list = entry["cameras"]
            if isinstance(name_list, list):
                indices = []
                for nm in name_list:
                    nstr = str(nm).strip().lower()
                    for i, n in enumerate(names):
                        if n and n.strip().lower() == nstr:
                            indices.append(i)
                            break
                if indices:
                    return indices
        return allowed

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

                allowed = resolve_streams(entry)
                stream_index = random.choice(allowed)
                playback_queue.put((path, stream_index))
                last_triggered[time_str] = now.timestamp()
                logger.info(f"Scheduled playback: {file_name} on stream {stream_index}")

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(60)  # Check every minute


def start_control_panel(playback_queue, num_streams, stream_names=None):
    """Start Flask control panel and scheduler in background threads."""
    # Ensure buttons.json exists
    path = _get_buttons_json_path()
    if not os.path.isfile(path):
        _save_buttons([])

    port = CONFIG.get("CONTROL_PANEL_PORT", 5000)
    app = create_app(playback_queue, num_streams, stream_names)

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
            args=(playback_queue, num_streams, stream_names),
            daemon=True
        )
        st.start()
        logger.info("Scheduled video scheduler started.")
