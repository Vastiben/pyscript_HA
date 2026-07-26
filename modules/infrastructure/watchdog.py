# watchdog.py

from datetime import datetime

BATTERY_ENTITY = "sensor.pave_numerique_36417_battery"

TELEGRAM_TARGET = None  # mets un chat_id si nécessaire
TWILIO_TARGET = "+41792763781"


def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _build_message(battery_value, problems):
    now_txt = datetime.now().strftime("%d.%m.%Y %H:%M")
    details = " ; ".join(problems)
    return (
        f"Alerte watchdog Home Assistant ({now_txt}) - {details}. "
        f"Batterie actuelle: {battery_value}."
    )


def _send_alert(message):
    log.info("▶ _send_alert démarré")

    service.call(
        "notify",
        "notifier_twilio",
        message=message,
        target=[TWILIO_TARGET]
    )

    log.info("✅ _send_alert — Twilio envoyé")


@time_trigger("cron(0 8,20 * * *)")
@service
def watchdog_hourly():
    log.info("▶ watchdog_hourly démarré")
    battery_raw = state.get(BATTERY_ENTITY)
    log.debug(f"  battery_raw={battery_raw}")

    battery = _safe_float(battery_raw)
    problems = []

    if battery is None:
        problems.append(f"batterie illisible sur {BATTERY_ENTITY}")
        log.warning(f"⚠ watchdog — batterie illisible : {BATTERY_ENTITY}")
    elif battery < 10:
        problems.append(f"batterie faible ({battery:.0f}%)")
        log.warning(f"⚠ watchdog — batterie faible : {battery:.0f}%")

    if problems:
        message = _build_message(battery_raw, problems)
        log.warning(f"🚨 watchdog_hourly — alerte envoyée : {message}")
        _send_alert(message)
    else:
        log.info("✅ watchdog_hourly — tout OK, aucune alerte")
