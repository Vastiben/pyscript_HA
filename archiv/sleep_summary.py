# pyscript/sleep_summary.py
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def parse_duration_to_seconds(d):
    """Parse MM:SS, H:MM:SS ou SS vers secondes"""
    parts = d.strip().split(":")
    try:
        if len(parts) == 1:   return int(parts[0])
        elif len(parts) == 2: return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        log.warning("Durée non parseable: %s", d)
    return 0

def seconds_to_readable(sec):
    h = int(sec) // 3600
    m = (int(sec) % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"

def parse_attr_list(attr_value):
    if isinstance(attr_value, list):
        return [str(v).strip() for v in attr_value]
    elif isinstance(attr_value, str):
        return [v.strip() for v in attr_value.split(",")]
    return []

def update_sleep_summary(**kwargs):
    """Met à jour sensor.sleep_last_night_summary avec les durées par type"""
    log.info("▶ update_sleep_summary démarré")

    attrs = state.getattr("sensor.sleep_data")
    if not attrs:
        log.error("❌ update_sleep_summary — impossible de lire sensor.sleep_data")
        return

    sleep_starts    = parse_attr_list(attrs.get("sleep_start", ""))
    sleep_durations = parse_attr_list(attrs.get("sleep_duration", ""))
    sleep_types     = parse_attr_list(attrs.get("sleep_type", ""))
    log.debug(f"  {len(sleep_starts)} entrées trouvées")

    if not sleep_starts:
        log.error("❌ update_sleep_summary — aucune donnée sleep_start")
        return

    tz = ZoneInfo("Europe/Zurich")
    now = datetime.now(tz)
    yesterday_18h = (now - timedelta(days=1)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    log.debug(f"  Fenêtre: {yesterday_18h.isoformat()} → {now.isoformat()}")

    durations  = {"Paradoxal": 0, "Lent": 0, "Profond": 0, "Réveillé": 0}
    nb_entries = 0
    actual_sleep_start = None
    actual_sleep_end   = None

    for start_str, dur_str, sleep_type in zip(sleep_starts, sleep_durations, sleep_types):
        try:
            start_dt = datetime.fromisoformat(start_str)
            if yesterday_18h <= start_dt <= now:
                dur_sec = parse_duration_to_seconds(dur_str)
                end_dt  = start_dt + timedelta(seconds=dur_sec)
                if sleep_type in durations:
                    durations[sleep_type] += dur_sec
                    nb_entries += 1
                    if actual_sleep_start is None or start_dt < actual_sleep_start:
                        actual_sleep_start = start_dt
                    if actual_sleep_end is None or end_dt > actual_sleep_end:
                        actual_sleep_end = end_dt
                else:
                    log.warning("⚠ update_sleep_summary — type inconnu: %s", sleep_type)
        except Exception as e:
            log.warning("⚠ update_sleep_summary — erreur entrée (%s): %s", start_str, str(e))

    total_sec = sum(durations.values())
    log.info(f"  {nb_entries} entrées | Total: {seconds_to_readable(total_sec)}")

    state.set(
        "sensor.sleep_last_night_summary",
        value=seconds_to_readable(total_sec),
        new_attributes={
            "friendly_name":  "Résumé sommeil nuit",
            "icon":           "mdi:sleep",
            "unit_of_measurement": "h",
            "paradoxal":      seconds_to_readable(durations["Paradoxal"]),
            "lent":           seconds_to_readable(durations["Lent"]),
            "profond":        seconds_to_readable(durations["Profond"]),
            "reveille":       seconds_to_readable(durations["Réveillé"]),
            "paradoxal_min":  round(durations["Paradoxal"] / 60, 1),
            "lent_min":       round(durations["Lent"] / 60, 1),
            "profond_min":    round(durations["Profond"] / 60, 1),
            "reveille_min":   round(durations["Réveillé"] / 60, 1),
            "total_min":      round(total_sec / 60, 1),
            "entries_count":  nb_entries,
            "window_start":   actual_sleep_start.isoformat() if actual_sleep_start else "",
            "window_end":     actual_sleep_end.isoformat()   if actual_sleep_end   else "",
            "last_updated":   now.isoformat(),
        }
    )
    log.info("✅ update_sleep_summary terminé")
