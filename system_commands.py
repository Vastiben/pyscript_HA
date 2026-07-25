"""
🔹 System Commands App
🔹 Reçoit les events depuis telegram_commands.py
🔹 Fournit /status et /reboot

Architecture:
Telegram → telegram_commands → pyscript_system → app

Logs: [SYS]
"""

from datetime import datetime


CONFIG = {
    "debug": True,
}


def dbg(msg):
    if CONFIG["debug"]:
        log.info("[SYS] " + str(msg))


def notify(msg, chat_id=None):
    data = {"message": str(msg)}
    if chat_id:
        data["target"] = chat_id
    service.call("telegram_bot", "send_message", **data)


def _safe_get(entity_id, default="n/a"):
    try:
        value = state.get(entity_id)
        if value in [None, "", "unknown", "unavailable"]:
            return default
        return str(value)
    except Exception:
        return default


@pyscript_compile
def _gather_system_info():
    import socket
    import subprocess

    out = {
        "hostname": "n/a",
        "local_ip": "n/a",
        "ip_brief": "n/a",
        "ip_route": "n/a",
        "wg_show": "n/a",
        "uptime": "n/a",
    }

    try:
        out["hostname"] = socket.gethostname()
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out["local_ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            out["local_ip"] = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass

    try:
        res = subprocess.run(
            ["ip", "-brief", "address"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        txt = (res.stdout or res.stderr or "").strip()
        if txt:
            out["ip_brief"] = txt
    except Exception as e:
        out["ip_brief"] = "err: " + str(e)

    try:
        res = subprocess.run(
            ["ip", "route"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        txt = (res.stdout or res.stderr or "").strip()
        if txt:
            out["ip_route"] = txt
    except Exception as e:
        out["ip_route"] = "err: " + str(e)

    try:
        res = subprocess.run(
            ["wg", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        txt = (res.stdout or res.stderr or "").strip()
        if txt:
            out["wg_show"] = txt
    except Exception as e:
        out["wg_show"] = "err: " + str(e)

    try:
        res = subprocess.run(
            ["uptime", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        txt = (res.stdout or res.stderr or "").strip()
        if txt:
            out["uptime"] = txt
    except Exception as e:
        out["uptime"] = "err: " + str(e)

    return out


@event_trigger("pyscript_system")
def pyscript_system_router(action=None, chat_id=None, text=None, ts=None, **kwargs):
    dbg("event reçu action=" + str(action))

    if action == "status":
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        sysinfo = task.executor(_gather_system_info)

        version = _safe_get("sensor.current_version")
        last_boot = _safe_get("sensor.last_boot")
        cpu = _safe_get("sensor.processor_use")
        mem = _safe_get("sensor.memory_use_percent")
        disk = _safe_get("sensor.disk_use_percent")
        cpu_temp = _safe_get("sensor.processor_temperature")
        ext_ip = _safe_get("sensor.myip")
        ha_uptime = _safe_get("sensor.uptime")

        msg = (
            "📡 HA Status\n"
            f"🕒 Heure: {now}\n"
            f"🖥️ Hostname: {sysinfo['hostname']}\n"
            f"🏠 IP locale: {sysinfo['local_ip']}\n"
            f"⏱️ Uptime OS: {sysinfo['uptime']}\n"
            f"🔄 Dernier boot: {last_boot}\n"
            f"🧩 Uptime HA: {ha_uptime}\n"
            f"🏷️ Version HA: {version}\n"
            f"🌍 IP publique: {ext_ip}\n"
            f"🧠 CPU: {cpu}%\n"
            f"💾 RAM: {mem}%\n"
            f"🗄️ Disk: {disk}%\n"
            f"🌡️ CPU temp: {cpu_temp}\n\n"
            f"📶 Interfaces:\n{sysinfo['ip_brief'][:1000]}\n\n"
            f"🛣️ Routes:\n{sysinfo['ip_route'][:700]}\n\n"
            f"🔐 WireGuard:\n{sysinfo['wg_show'][:1200]}"
        )

        notify(msg, chat_id)
        return

    if action == "reboot":
        notify("♻️ Commande /reboot reçue. Redémarrage de Home Assistant en cours...", chat_id)
        task.sleep(2)
        service.call("homeassistant", "restart")
        return

    notify("❌ Action système inconnue: " + str(action), chat_id)
