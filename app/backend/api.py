"""ユーザー投稿プリセット用 REST API。

Flask の route として登録される。
"""

import os
from functools import wraps

from flask import jsonify, request

from app import app
from app.backend.user_presets import (
    approve_preset,
    delete_preset,
    load_user_presets,
)

server = app.server
_ADMIN_TOKEN = os.environ.get("PRESET_ADMIN_TOKEN", "")


def _require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _ADMIN_TOKEN:
            return jsonify(
                {"status": "error", "message": "admin token not configured"}
            ), 503
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {_ADMIN_TOKEN}":
            return jsonify({"status": "error", "message": "unauthorized"}), 401
        return f(*args, **kwargs)

    return wrapper


@server.route("/api/presets/admin", methods=["POST"])
@_require_admin
def api_admin_action():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "invalid JSON"}), 400
    action = data.get("action")
    key = data.get("key", "")
    if action == "approve":
        if approve_preset(key):
            return jsonify({"status": "ok"})
        return jsonify({"status": "error", "message": "preset not found"}), 404
    if action == "delete":
        if delete_preset(key):
            return jsonify({"status": "ok"})
        return jsonify({"status": "error", "message": "preset not found"}), 404
    return jsonify(
        {"status": "error", "message": "action must be 'approve' or 'delete'"}
    ), 400


@server.route("/api/presets/admin/list", methods=["GET"])
@_require_admin
def api_admin_list():
    presets = load_user_presets()
    return jsonify({"status": "ok", "presets": presets})
