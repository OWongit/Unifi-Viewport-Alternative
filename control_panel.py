"""
Flask control panel for triggering video playback on stream windows.
Serves a web UI with buttons per MP4 file and runs the scheduled video scheduler.
"""
import json
import os
import random
import shutil
import threading
import time
import logging
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
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


def _get_auth_path():
    """Return path to auth.json."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.json")


def _get_ip_access_path():
    """Return path to ip_access.json."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip_access.json")


def _get_play_log_path():
    """Return path to play_log.json."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "play_log.json")


def _load_play_log():
    """Load play log, prune to last 7 days, cap at 5000."""
    path = _get_play_log_path()
    default = []
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        cutoff = time.time() - (7 * 24 * 3600)
        pruned = [e for e in data if isinstance(e, dict) and e.get("ts", 0) > cutoff][-5000:]
        return pruned
    except (json.JSONDecodeError, OSError):
        return []


def _append_play_log(filename: str):
    """Append a play event to the log."""
    path = _get_play_log_path()
    log = _load_play_log()
    log.append({"file": filename, "ts": time.time()})
    log = log[-5000:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=0)
    except OSError:
        pass


def _get_advanced_schedule_path():
    """Return path to advanced_schedule.json."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "advanced_schedule.json")


def _load_auth():
    """Load auth credentials. Returns None if not configured."""
    path = _get_auth_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_ip_access():
    """Load ip_access.json. Returns {ip_last_action, blocked_ips}."""
    path = _get_ip_access_path()
    default = {"ip_last_action": {}, "blocked_ips": []}
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "ip_last_action": data.get("ip_last_action", {}),
            "blocked_ips": data.get("blocked_ips", [])
        }
    except (json.JSONDecodeError, OSError):
        return default


def _save_ip_access(ip_last_action, blocked_ips):
    """Save ip_access.json."""
    path = _get_ip_access_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ip_last_action": ip_last_action, "blocked_ips": blocked_ips}, f, indent=2)


def _get_app_settings_path():
    """Return path to app_settings.json."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_settings.json")


def _load_app_settings():
    """Load app_settings.json. Returns {controls_disabled: bool}."""
    path = _get_app_settings_path()
    default = {"controls_disabled": False}
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"controls_disabled": bool(data.get("controls_disabled", False))}
    except (json.JSONDecodeError, OSError):
        return default


def _save_app_settings(controls_disabled):
    """Save app_settings.json."""
    path = _get_app_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"controls_disabled": controls_disabled}, f, indent=2)


def _record_ip_action(ip, action="play"):
    """Record or overwrite the most recent action for an IP."""
    data = _load_ip_access()
    data["ip_last_action"][ip] = {"ts": time.time(), "action": action}
    # Prune entries older than 24h
    cutoff = time.time() - (24 * 3600)
    data["ip_last_action"] = {k: v for k, v in data["ip_last_action"].items()
                             if v.get("ts", 0) > cutoff}
    _save_ip_access(data["ip_last_action"], data["blocked_ips"])


def _load_advanced_schedule():
    """Load advanced_schedule.json."""
    path = _get_advanced_schedule_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_advanced_schedule(entries):
    """Save advanced_schedule.json."""
    path = _get_advanced_schedule_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def _is_file_in_advanced_schedule(filename):
    """Check if filename is referenced in advanced schedule."""
    for entry in _load_advanced_schedule():
        if isinstance(entry, dict) and entry.get("file") == filename:
            return True
    return False


def create_app(playback_queue, num_streams, stream_names=None):
    """Create Flask app with routes. Used by start_control_panel."""
    global _playback_queue, _num_streams, _stream_names
    _playback_queue = playback_queue
    _num_streams = max(1, num_streams)
    _stream_names = stream_names if stream_names and len(stream_names) == _num_streams else [
        f"Camera {i + 1}" for i in range(_num_streams)
    ]

    app = Flask(__name__, static_folder=_get_static_folder())
    app.secret_key = CONFIG.get("SECRET_KEY", "dev-secret-key")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    def _get_client_ip():
        return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip() or "unknown"

    def require_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth = _load_auth()
            if not auth:
                return jsonify({"error": "Advanced settings not configured"}), 401
            if not session.get("authenticated"):
                return jsonify({"error": "Authentication required"}), 401
            return f(*args, **kwargs)
        return decorated

    def _get_images_folder():
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

    @app.route("/")
    def index():
        return send_from_directory(_get_static_folder(), "index.html")

    @app.route("/favicon.png")
    def favicon():
        return send_from_directory(_get_images_folder(), "favicon.png")

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        auth = _load_auth()
        if not auth:
            return jsonify({"error": "Advanced settings not configured"}), 401
        data = request.get_json() or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        if username != auth.get("username") or not check_password_hash(auth.get("password_hash", ""), password):
            return jsonify({"error": "Invalid credentials"}), 401
        session["authenticated"] = True
        return jsonify({"ok": True})

    @app.route("/api/auth/check", methods=["GET"])
    def auth_check():
        auth = _load_auth()
        if not auth:
            return jsonify({"configured": False, "authenticated": False})
        return jsonify({"configured": True, "authenticated": bool(session.get("authenticated"))})

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        session.pop("authenticated", None)
        return jsonify({"ok": True})

    @app.route("/api/streams", methods=["GET"])
    def get_streams():
        """Return stream count, indices, camera names, and controls_disabled."""
        settings = _load_app_settings()
        return jsonify({
            "count": _num_streams,
            "streams": [{"index": i, "name": _stream_names[i]} for i in range(_num_streams)],
            "controls_disabled": settings["controls_disabled"]
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
            if not _is_file_in_advanced_schedule(filename):
                path = _resolve_video_path(filename)
                if path and os.path.isfile(path):
                    try:
                        os.remove(path)
                        logger.info(f"Deleted video file: {filename}")
                    except OSError as e:
                        logger.warning(f"Could not delete video file {filename}: {e}")
            else:
                logger.info(f"Kept video file {filename} (in advanced schedule)")
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
        settings = _load_app_settings()
        if settings.get("controls_disabled"):
            return jsonify({"ok": False, "error": "Button controls are disabled"}), 403
        client_ip = _get_client_ip()
        data = _load_ip_access()
        if client_ip in data["blocked_ips"]:
            return jsonify({"ok": False, "error": "Access denied"}), 403

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
        # Put (path, allowed_streams) - GUI picks slot with earliest start time
        _playback_queue.put((path, allowed))
        _record_ip_action(client_ip, "play")
        _append_play_log(filename)
        return jsonify({"ok": True, "streams": allowed})

    @app.route("/api/stats", methods=["GET"])
    def get_stats():
        """Return storage, button count, and most-used stats."""
        base = os.path.dirname(os.path.abspath(__file__))
        try:
            usage = shutil.disk_usage(base)
            storage_used_gb = round(usage.used / (1024 ** 3), 1)
            storage_total_gb = round(usage.total / (1024 ** 3), 1)
        except OSError:
            storage_used_gb = storage_total_gb = 0
        buttons = _load_buttons()
        button_count = len(buttons)
        file_to_name = {b.get("file"): b.get("name") for b in buttons if b.get("file") and b.get("name")}
        now = time.time()
        cutoff_24h = now - (24 * 3600)
        cutoff_week = now - (7 * 24 * 3600)
        log = _load_play_log()
        counts_24h = {}
        counts_week = {}
        for e in log:
            f = e.get("file")
            ts = e.get("ts", 0)
            if not f:
                continue
            if ts > cutoff_24h:
                counts_24h[f] = counts_24h.get(f, 0) + 1
            if ts > cutoff_week:
                counts_week[f] = counts_week.get(f, 0) + 1
        def top(counts):
            if not counts:
                return None
            f = max(counts, key=counts.get)
            return {"file": f, "name": file_to_name.get(f, f), "count": counts[f]}
        return jsonify({
            "storage_used_gb": storage_used_gb,
            "storage_total_gb": storage_total_gb,
            "button_count": button_count,
            "most_used_24h": top(counts_24h),
            "most_used_week": top(counts_week)
        })

    @app.route("/api/videos", methods=["GET"])
    def get_videos():
        """List video filenames in VIDEOS_FOLDER."""
        folder = _get_videos_folder()
        if not os.path.isdir(folder):
            return jsonify([])
        files = []
        for f in os.listdir(folder):
            if f.lower().endswith((".mp4", ".mov")):
                files.append(f)
        return jsonify(sorted(files))

    @app.route("/api/advanced/ips", methods=["GET"])
    @require_auth
    def get_advanced_ips():
        data = _load_ip_access()
        cutoff = time.time() - (24 * 3600)
        pruned = {k: v for k, v in data["ip_last_action"].items() if v.get("ts", 0) > cutoff}
        return jsonify({"ip_last_action": pruned, "blocked_ips": data["blocked_ips"]})

    @app.route("/api/advanced/ips/block", methods=["POST"])
    @require_auth
    def block_ip():
        data = request.get_json() or {}
        ip = (data.get("ip") or "").strip()
        if not ip:
            return jsonify({"error": "IP required"}), 400
        data = _load_ip_access()
        if ip not in data["blocked_ips"]:
            data["blocked_ips"].append(ip)
            _save_ip_access(data["ip_last_action"], data["blocked_ips"])
        return jsonify({"ok": True})

    @app.route("/api/advanced/ips/unblock", methods=["POST"])
    @require_auth
    def unblock_ip():
        data = request.get_json() or {}
        ip = (data.get("ip") or "").strip()
        if not ip:
            return jsonify({"error": "IP required"}), 400
        data = _load_ip_access()
        data["blocked_ips"] = [x for x in data["blocked_ips"] if x != ip]
        _save_ip_access(data["ip_last_action"], data["blocked_ips"])
        return jsonify({"ok": True})

    @app.route("/api/advanced/controls", methods=["GET"])
    @require_auth
    def get_advanced_controls():
        settings = _load_app_settings()
        return jsonify({"controls_disabled": settings["controls_disabled"]})

    @app.route("/api/advanced/controls", methods=["POST"])
    @require_auth
    def set_advanced_controls():
        data = request.get_json() or {}
        disabled = bool(data.get("controls_disabled", False))
        _save_app_settings(disabled)
        return jsonify({"ok": True, "controls_disabled": disabled})

    @app.route("/api/advanced/schedule", methods=["GET"])
    @require_auth
    def get_advanced_schedule():
        return jsonify(_load_advanced_schedule())

    @app.route("/api/advanced/schedule", methods=["POST"])
    @require_auth
    def add_advanced_schedule():
        data = request.get_json() or {}
        time_str = (data.get("time") or "").strip()
        file_name = (data.get("file") or "").strip()
        if not time_str or not file_name:
            return jsonify({"error": "time and file required"}), 400
        if ".." in file_name or "/" in file_name or os.path.sep in file_name:
            return jsonify({"error": "Invalid filename"}), 400
        entry = {"time": time_str, "file": file_name}
        if "stream" in data and isinstance(data["stream"], int) and 0 <= data["stream"] < _num_streams:
            entry["stream"] = data["stream"]
        elif "streams" in data and isinstance(data["streams"], list):
            valid = [s for s in data["streams"] if isinstance(s, int) and 0 <= s < _num_streams]
            if valid:
                entry["streams"] = valid
        schedule = _load_advanced_schedule()
        schedule.append(entry)
        _save_advanced_schedule(schedule)
        return jsonify({"ok": True})

    @app.route("/api/advanced/schedule/<int:index>", methods=["DELETE"])
    @require_auth
    def delete_advanced_schedule(index):
        schedule = _load_advanced_schedule()
        if index < 0 or index >= len(schedule):
            return jsonify({"error": "Invalid index"}), 400
        schedule.pop(index)
        _save_advanced_schedule(schedule)
        return jsonify({"ok": True})

    return app


def _run_scheduler(playback_queue, num_streams, stream_names=None):
    """Background thread: check SCHEDULED_VIDEOS and advanced_schedule every minute."""
    from datetime import datetime

    config_scheduled = CONFIG.get("SCHEDULED_VIDEOS", [])
    advanced = _load_advanced_schedule()
    scheduled = list(config_scheduled) + list(advanced)
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

                # Avoid firing same (time, file) multiple times in same minute
                trigger_key = (time_str, file_name)
                last = last_triggered.get(trigger_key, 0)
                if now.timestamp() - last < 55:
                    continue

                path = os.path.join(folder, file_name)
                if not os.path.isfile(path):
                    logger.warning(f"Scheduled video not found: {path}")
                    continue

                allowed = resolve_streams(entry)
                playback_queue.put((path, allowed))
                last_triggered[trigger_key] = now.timestamp()
                logger.info(f"Scheduled playback: {file_name} on streams {allowed}")

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
    has_schedule = CONFIG.get("SCHEDULED_VIDEOS") or _load_advanced_schedule()
    if has_schedule:
        st = threading.Thread(
            target=_run_scheduler,
            args=(playback_queue, num_streams, stream_names),
            daemon=True
        )
        st.start()
        logger.info("Scheduled video scheduler started.")
