import json, os, platform, subprocess, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, render_template, send_from_directory

APP_PORT = 5000
DEVICES_FILE = "devices.json"

app = Flask(__name__)


# ---------- Storage ----------
def load_devices():
    if not os.path.exists(DEVICES_FILE):
        save_devices([])
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Ensure each device has an id
    updated = False
    for d in data:
        if "id" not in d:
            d["id"] = str(uuid.uuid4())
            updated = True
    if updated:
        save_devices(data)
    return data

def save_devices(devices):
    with open(DEVICES_FILE, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=2)


# ---------- ICMP Ping ----------
def ping_host(ip: str, timeout_ms: int = 1200) -> bool:
    """
    Returns True if host responds to a single ICMP ping.
    Uses the system 'ping' command so no special privileges are needed.
    """
    sysname = platform.system().lower()
    try:
        if sysname == "windows":
            # -n 1: one echo; -w timeout ms
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        else:
            # Linux (Codespaces): -c 1: one echo; -W timeout seconds
            # Convert ms -> seconds, min 1s to avoid '0' (some pings reject 0)
            secs = max(1, int(round(timeout_ms / 1000)))
            cmd = ["ping", "-c", "1", "-W", str(secs), ip]

        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False


def bulk_status(devices):
    """
    Pings many devices in parallel.
    Returns list: [{id, name, ip, online: bool}]
    """
    out = []
    with ThreadPoolExecutor(max_workers=min(64, max(4, len(devices)))) as ex:
        futures = {ex.submit(ping_host, d["ip"]): d for d in devices}
        for fut in as_completed(futures):
            d = futures[fut]
            online = False
            try:
                online = fut.result()
            except Exception:
                online = False
            out.append({
                "id": d["id"],
                "name": d["name"],
                "ip": d["ip"],
                "online": online
            })
    # keep stable order by name then ip
    out.sort(key=lambda x: (x["name"].lower(), x["ip"]))
    return out


# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/devices", methods=["GET"])
def get_devices():
    return jsonify(load_devices())

@app.route("/api/devices", methods=["POST"])
def add_device():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    ip = (data.get("ip") or "").strip()
    if not name or not ip:
        return jsonify({"error": "name and ip are required"}), 400

    devices = load_devices()
    # avoid duplicates on same IP
    if any(d["ip"] == ip for d in devices):
        return jsonify({"error": "device with this IP already exists"}), 409

    new_dev = {"id": str(uuid.uuid4()), "name": name, "ip": ip}
    devices.append(new_dev)
    save_devices(devices)
    return jsonify(new_dev), 201

@app.route("/api/devices/<dev_id>", methods=["DELETE"])
def delete_device(dev_id):
    devices = load_devices()
    new_list = [d for d in devices if d["id"] != dev_id]
    if len(new_list) == len(devices):
        return jsonify({"error": "not found"}), 404
    save_devices(new_list)
    return jsonify({"ok": True})

@app.route("/api/status", methods=["GET"])
def all_status():
    devices = load_devices()
    return jsonify(bulk_status(devices))


# Serve devices.json if you want to inspect it (optional)
@app.route("/devices.json")
def serve_devices_json():
    return send_from_directory(".", "devices.json", mimetype="application/json")


if __name__ == "__main__":
    # Create empty devices file if missing
    if not os.path.exists(DEVICES_FILE):
        save_devices([
            {"id": str(uuid.uuid4()), "name": "Google DNS", "ip": "8.8.8.8"},
            {"id": str(uuid.uuid4()), "name": "Cloudflare DNS", "ip": "1.1.1.1"}
        ])
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
