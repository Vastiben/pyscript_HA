# pyscript/health.py
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from homeassistant.util.dt import as_utc
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)


def parse_duration_to_seconds(d):
    """Parse MM:SS, H:MM:SS ou SS vers secondes."""
    parts = d.strip().split(":")
    try:
        if len(parts) == 1:
            return int(parts[0])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return (
                int(parts[0]) * 3600
                + int(parts[1]) * 60
                + int(parts[2])
            )
    except ValueError:
        log.warning("Durée non parseable: %s", d)
    return 0


def seconds_to_readable(sec):
    """Convertit les secondes en format lisible."""
    h = int(sec) // 3600
    m = (int(sec) % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def _parse_multiline_attr(json_data, key):
    """Extrait une liste de tokens depuis un attribut JSON.

    L'attribut peut être :
    - une string multiline  (séparateur \\n)
    - une liste Python
    - None / absent
    """
    raw = json_data.get(key, "")
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    return [s.strip() for s in str(raw).split("\n") if s.strip()]


@webhook_trigger("health_sync_bg", methods=["POST"], local_only=True)
def health_sync_update(**kwargs):
    """Reçoit les données health via webhook POST et met à jour HA."""
    json_data = kwargs.get("payload", {})
    log.warning("kwargs keys: %s", list(kwargs.keys()))
    log.warning("json: %s", kwargs.get("json"))
    log.warning("data: %s", kwargs.get("data"))
    log.warning("body: %s", kwargs.get("body"))

    if not json_data:
        log.warning("health_sync_bg: payload JSON vide")
        return

    _health_notify(json_data)
    _update_hrv(json_data)
    _update_sleep_summary(json_data)


# =============================================================
# Séries HRV
# =============================================================
def _update_hrv(json_data):
    """Injecte les statistiques HRV dans le recorder HA."""
    tz = ZoneInfo("Europe/Zurich")
    now_str = datetime.now(tz).isoformat()

    hrv_inst = json_data.get("hrv_inst", 0)
    hrv_start = _parse_multiline_attr(json_data, "hrv_start")
    hrv_value = _parse_multiline_attr(json_data, "hrv_value")

    metadata = StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name="HRV",
        source="recorder",
        statistic_id="sensor.health_hrv",
        unit_of_measurement="ms",
        unit_class=None,
    )

    stats = [
        StatisticData(
            start=datetime.fromisoformat(s).replace(
                minute=0, second=0, microsecond=0
            ),
            mean=float(v),
            min=float(v),
            max=float(v),
        )
        for s, v in zip(hrv_start, hrv_value)
        if float(v) > 0
    ]

    heure_actuelle = datetime.now(tz).replace(
        minute=0, second=0, microsecond=0
    )
    stats.append(StatisticData(
        start=heure_actuelle,
        mean=float(hrv_inst),
        min=float(hrv_inst),
        max=float(hrv_inst),
    ))

    state.set(
        "sensor.health_hrv",
        new_attributes={"last_sync": now_str},
    )

    log.warning("Stats: %s", stats)
    async_import_statistics(hass, metadata, stats)
    log.warning("HRV: %d stats injectées", len(stats))
    log.warning("_update_hrv terminé")


# =============================================================
# Résumé sommeil (50 entrées)
# =============================================================
def _update_sleep_summary(json_data):
    """Calcule et stocke le résumé de la nuit depuis json_data."""
    sleep_start_raw    = json_data.get("sleep_start", "")
    sleep_duration_raw = json_data.get("sleep_duration", "")
    sleep_type_raw     = json_data.get("sleep_type", "")

    sleep_starts    = _parse_multiline_attr(json_data, "sleep_start")
    sleep_durations = _parse_multiline_attr(json_data, "sleep_duration")
    sleep_types     = _parse_multiline_attr(json_data, "sleep_type")

    if not sleep_starts:
        log.warning("update_sleep_summary: aucune donnée sleep_start")
        return

    tz = ZoneInfo("Europe/Zurich")
    now = datetime.now(tz)
    yesterday_18h = (now - timedelta(days=1)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )

    midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc   = as_utc(midnight_today)

    durations  = {"Paradoxal": 0, "Lent": 0, "Profond": 0, "Réveillé": 0}
    nb_entries = 0
    actual_sleep_start = None
    actual_sleep_end   = None

    for start_str, dur_str, sleep_type in zip(
        sleep_starts, sleep_durations, sleep_types
    ):
        try:
            start_dt = datetime.fromisoformat(start_str)
            if yesterday_18h <= start_dt <= now:
                dur_sec = parse_duration_to_seconds(dur_str)
                end_dt  = start_dt + timedelta(seconds=dur_sec)

                if sleep_type in durations:
                    durations[sleep_type] += dur_sec
                    nb_entries += 1
                    if (
                        actual_sleep_start is None
                        or start_dt < actual_sleep_start
                    ):
                        actual_sleep_start = start_dt
                    if (
                        actual_sleep_end is None
                        or end_dt > actual_sleep_end
                    ):
                        actual_sleep_end = end_dt
                else:
                    log.warning("Type inconnu: %s", sleep_type)
        except Exception as e:
            log.warning(
                "Erreur entrée (%s): %s", start_str, str(e)
            )

    total_sec = (
        durations["Paradoxal"]
        + durations["Lent"]
        + durations["Profond"]
        + durations["Réveillé"]
    )
    log.warning(
        "sleep_summary: %d entrées | Total: %s",
        nb_entries, seconds_to_readable(total_sec),
    )

    state.set(
        "sensor.sleep_last_night_summary",
        value=seconds_to_readable(total_sec),
        new_attributes={
            "friendly_name":       "Résumé sommeil nuit",
            "icon":                "mdi:sleep",
            "unit_of_measurement": "h",
            "paradoxal":           seconds_to_readable(durations["Paradoxal"]),
            "lent":                seconds_to_readable(durations["Lent"]),
            "profond":             seconds_to_readable(durations["Profond"]),
            "reveille":            seconds_to_readable(durations["Réveillé"]),
            "paradoxal_min":       round(durations["Paradoxal"] / 60, 1),
            "lent_min":            round(durations["Lent"] / 60, 1),
            "profond_min":         round(durations["Profond"] / 60, 1),
            "reveille_min":        round(durations["Réveillé"] / 60, 1),
            "total_min":           round(total_sec / 60, 1),
            "entries_count":       nb_entries,
            "window_start":        (
                actual_sleep_start.isoformat()
                if actual_sleep_start else ""
            ),
            "window_end":          (
                actual_sleep_end.isoformat()
                if actual_sleep_end else ""
            ),
            "last_updated":        midnight_today.isoformat(),
        }
    )

    metadata = StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name="Résumé sommeil nuit",
        source="recorder",
        statistic_id="sensor.sleep_last_night_summary",
        unit_of_measurement="h",
        unit_class=None,
    )
    stat = StatisticData(
        start=midnight_utc, state=total_sec / 3600, sum=None, mean=None
    )
    async_import_statistics(hass, metadata, [stat])
    log.warning("_update_sleep_summary terminé")


# =============================================================
# Notification persistante dans l'UI HA
# =============================================================
def _health_notify(json_data):
    """Crée une notification persistante avec le contenu du payload."""
    parts = [f"{k}: {v}" for k, v in json_data.items()]
    msg = "\n".join(parts)
    service.call(
        "persistent_notification",
        "create",
        title="health_sync_bg reçu",
        message=msg,
    )
    log.warning("_health_notify terminé")
