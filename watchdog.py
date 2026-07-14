# watchdog.py

from datetime import datetime

BATTERY_ENTITY = "sensor.pave_numerique_36417_battery"
REMOTE_ENTITY = "sensor.remote_connection_to_ha_secours_local_8123"

TELEGRAM_TARGET = None  # mets un chat_id si nécessaire
TWILIO_TARGET = "+41792763781"

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
        f"État connexion distante: {remote_value}."
    )

def _send_alert(message):
    # ── Telegram (désactivé) ──────────────────────────────────────────────────
    # telegram_data = {
    #     "title": "Alerte watchdog",
    #     "message": message,
    # }
    # if TELEGRAM_TARGET is not None:
    #     telegram_data["target"] = TELEGRAM_TARGET
    # service.call("telegram_bot", "send_message", **telegram_data)
    # ─────────────────────────────────────────────────────────────────────────

    service.call(
        "notify",
        "notifier_twilio",
        message=message,
        target=[TWILIO_TARGET]
    )

@time_trigger("cron(0 8,20 * * *)")
def watchdog_hourly():
    battery_raw = state.get(BATTERY_ENTITY)
    remote_raw = state.get(REMOTE_ENTITY)

    battery = _safe_float(battery_raw)
    remote_ok = _is_remote_ok(remote_raw)

    problems = []

    if battery is None:
        problems.append(f"batterie illisible sur {BATTERY_ENTITY}")
    elif battery < 10:
        problems.append(f"batterie faible ({battery:.0f}%)")

    if not remote_ok:
        problems.append(f"connexion distante inactive ({REMOTE_ENTITY}={remote_raw})")

    if problems:
        message = _build_message(battery_raw, remote_raw, problems)
        log.warning(message)
        _send_alert(message)
