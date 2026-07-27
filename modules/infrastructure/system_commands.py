from datetime import datetime
import socket
import subprocess

# =========================================================
# CONFIG - A ADAPTER PROGRESSIVEMENT
# =========================================================

# Entités très probables / génériques
CORE_ENTITIES = {
    "Home Assistant": [
        ("Version", "sensor.current_version"),
        ("Dernier boot", "sensor.last_boot"),
    ],
    "Système": [
        ("CPU %", "sensor.processor_use"),
        ("RAM %", "sensor.memory_use_percent"),
        ("Disque %", "sensor.disk_use_percent"),
        ("Temp CPU", "sensor.processor_temperature"),
    ],
}

# Mets ici TES entités réellement utiles
CUSTOM_ENTITIES = {
    "Réseau": [
        ("HA secours", "binary_sensor.ping_ha_slave"),
        ("Routeur", "binary_sensor.ping_router"),
        ("Internet", "binary_sensor.ping_internet"),
    ],
    "Services": [
        ("MQTT", "binary_sensor.mqtt_connected"),
        ("ESPHome", "binary_sensor.esphome_status"),
    ],
}

# Cibles réseau "texte" pour contrôle brut
NETWORK_TARGETS = [
    ("HA principal", "192.168.1.121"),
    ("HA secours", "192.168.1.139"),
    ("WG serveur", "172.27.66.1"),
]

# Interfaces possibles selon plateforme
IP_CANDIDATES = [
    "sensor.ipv4_address_end0",
    "sensor.ipv4_address_eth0",
    "sensor.ipv4_address_wlan0",
]

# =========================================================
# HELPERS
# =========================================================

def _safe_state(entity_id, default="n/a"):
    try:
        val = state.get(entity_id)
        if val in [None, "unknown", "unavailable", "None", "none", ""]:
            return default
        return str(val)
    except Exception:
        return default

def _first_existing_state(entity_ids, default="n/a"):
    for ent in entity_ids:
        val = _safe_state(ent, default=None)
        if val not in [None, "unknown", "unavailable", "None", "none", ""]:
            return val
    return default

def _run_cmd(cmd, timeout=4):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (res.stdout or res.stderr or "").strip()
        return out if out else "n/a"
    except Exception as e:
        return f"err: {e}"

def _hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "n/a"

def _local_ip_fallback():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "n/a"

def _local_ip():
    ip = _first_existing_state(IP_CANDIDATES, default=None)
    return ip if ip else _local_ip_fallback()

def _uptime():
    return _run_cmd(["uptime", "-p"], timeout=4)

def _ping_host(host):
    out = _run_cmd(["ping", "-c", "1", "-W", "1", host], timeout=3)
    if out.startswith("err:"):
        return "n/a"
    return "OK" if "1 received" in out or "1 packets received" in out else "KO"

def _wg_summary():
    out = _run_cmd(["wg", "show"], timeout=4)
    if len(out) > 1200:
        out = out[:1200] + "\n..."
    return out

def _format_entity_block(block_name, items):
    lines = [f"{block_name}"]
    for label, entity_id in items:
        lines.append(f"- {label}: {_safe_state(entity_id)}")
    return lines

def _build_status_message():
    lines = []
    lines.append("📡 HA Status")
    lines.append(f"🕒 Heure: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    lines.append(f"🖥️ Hostname: {_hostname()}")
    lines.append(f"🏠 IP locale: {_local_ip()}")
    lines.append(f"⏱️ Uptime: {_uptime()}")
    lines.append("")

    for section, items in CORE_ENTITIES.items():
        lines.extend(_format_entity_block(section, items))
        lines.append("")

    for section, items in CUSTOM_ENTITIES.items():
        lines.extend(_format_entity_block(section, items))
        lines.append("")

    lines.append("Tests réseau")
    for label, host in NETWORK_TARGETS:
        lines.append(f"- {label} ({host}): {_ping_host(host)}")
    lines.append("")

    lines.append("WireGuard")
    lines.append(_wg_summary())

    msg = "\n".join(lines)
    if len(msg) > 3800:
        msg = msg[:3800] + "\n..."
    return msg

# =========================================================
# TELEGRAM COMMANDS
# =========================================================

@event_trigger("telegram_command", "command == '/status'")
def telegram_status(command=None, chat_id=None, user_id=None, args=None, **kwargs):
    msg = _build_status_message()
    service.call(
        "telegram_bot",
        "send_message",
        chat_id=chat_id,
        message=msg
    )

@event_trigger("telegram_command", "command == '/reboot'")
def telegram_reboot(command=None, chat_id=None, user_id=None, args=None, **kwargs):
    service.call(
        "telegram_bot",
        "send_message",
        chat_id=chat_id,
        message="♻️ Commande /reboot reçue. Redémarrage de Home Assistant en cours..."
    )
    task.sleep(2)
    service.call("homeassistant", "restart")
