# watchdog.py

from datetime import datetime

BATTERY_ENTITY = "sensor.pave_numerique_36417_battery"
REMOTE_ENTITY = "sensor.remote_home_assistant_update"

TELEGRAM_TARGET = None  # optionnel: mets un chat_id si ton service le demande
TWILIO_SERVICE = "notify.notifier_twilio"  # adapte si ton service Twilio a un autre nom

def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return None

def _is_remote_ok(value):
    if value is None:
        return False
    txt = str(value).strip().lower()
    return txt not in ["unknown", "unavailable", "off", "disconnected", "down", "false", "0", "none", ""]

def _build_message(battery_value, remote_value, problems):
    now_txt = datetime.now().strftime("%d.%m.%Y %H:%M")
    details = " ; ".join(problems)
    return (
        f"Alerte watchdog Home Assistant ({now_txt}) - {details}. "
        f"Batterie actuelle: {battery_value}. "
        f"Etat connexion distante: {remote_value}."
    )

def _send_alert(message):
    data = {
        "title": "Alerte watchdog",
        "message": message,
    }

    if TELEGRAM_TARGET is not None:
        data["target"] = TELEGRAM_TARGET

    service.call("telegram_bot", "send_message", **data)
    service.call("notify", "twilio", target=41792763781, message=message)

@time_trigger("cron(0 * * * *)")
def watchdog_hourly():
    battery_raw = state.get(BATTERY_ENTITY)
    remote_raw = state.get(REMOTE_ENTITY)

    battery = _safe_float(battery_raw)
    remote_ok = _is_remote_ok(remote_raw)

    problems = []

    if battery 
