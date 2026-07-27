from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from open_meteo_solar_forecast import OpenMeteoSolarForecast

TIMEZONE = "Europe/Zurich"

LATITUDE = 46.46
LONGITUDE = 6.84
DECLINATION = 35          # inclinaison panneaux
AZIMUTH = 180             # 180 = sud, à adapter
DC_KWP = 9.6              # puissance crête DC totale

SENSOR_PREFIX = "sensor.solar_forecast_tomorrow_h"
SUMMARY_SENSOR = "sensor.solar_forecast_tomorrow_summary"


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _get_attr(obj, *names):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _normalize_point(raw_point):
    dt_val = _get_attr(raw_point, "datetime", "period_start", "time", "date")
    power_val = _get_attr(
        raw_point,
        "power",
        "watts",
        "w",
        "pv_estimate",
        "pv_estimate_w",
        "value",
    )

    if dt_val is None:
        return None

    if isinstance(dt_val, str):
        try:
            dt_obj = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
        except Exception:
            return None
    else:
        dt_obj = dt_val

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=ZoneInfo(TIMEZONE))
    else:
        dt_obj = dt_obj.astimezone(ZoneInfo(TIMEZONE))

    return {
        "datetime": dt_obj,
        "power": round(_safe_float(power_val, 0.0), 1),
    }


def _extract_hourly_points(estimate):
    candidates = [
        _get_attr(estimate, "detailed_forecast"),
        _get_attr(estimate, "detailedForecast"),
        _get_attr(estimate, "forecast"),
        _get_attr(estimate, "forecasts"),
        _get_attr(estimate, "hourly"),
        _get_attr(estimate, "hourly_forecast"),
        _get_attr(estimate, "watts"),
        _get_attr(estimate, "power_production"),
    ]

    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            points = []
            for item in candidate:
                point = _normalize_point(item)
                if point:
                    points.append(point)
            if points:
                return points

    return []


async def _build_tomorrow_points():
    tz = ZoneInfo(TIMEZONE)
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()

    async with OpenMeteoSolarForecast(
        latitude=LATITUDE,
        longitude=LONGITUDE,
        declination=DECLINATION,
        azimuth=AZIMUTH,
        dc_kwp=DC_KWP,
    ) as forecast:
        estimate = await forecast.estimate()

    points = _extract_hourly_points(estimate)
    tomorrow_points = [p for p in points if p["datetime"].date() == tomorrow]

    by_hour = {p["datetime"].hour: p for p in tomorrow_points}
    result = []

    for hour in range(24):
        dt_hour = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day, hour, 0, 0, tzinfo=tz
        )
        power = by_hour.get(hour, {}).get("power", 0.0)
        result.append(
            {
                "datetime": dt_hour.isoformat(),
                "hour": hour,
                "power": round(power, 1),
            }
        )

    return result


@time_trigger("cron(0 18 * * *)")
@time_trigger("startup")
async def update_solar_forecast_tomorrow():
    try:
        forecast_24h = await _build_tomorrow_points()
        total_wh = sum(item["power"] for item in forecast_24h)

        for item in forecast_24h:
            entity_id = f"{SENSOR_PREFIX}{item['hour']:02d}"
            state.set(
                entity_id,
                value=item["power"],
                new_attributes={
                    "friendly_name": f"Prévision solaire demain {item['hour']:02d}h",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "state_class": "measurement",
                    "forecast_datetime": item["datetime"],
                    "forecast_day": "tomorrow",
                    "source": "open-meteo-solar-forecast",
                    "updated_at": datetime.now(ZoneInfo(TIMEZONE)).isoformat(),
                },
            )

        state.set(
            SUMMARY_SENSOR,
            value=len(forecast_24h),
            new_attributes={
                "friendly_name": "Prévision solaire demain résumé",
                "forecast_day": "tomorrow",
                "points_count": len(forecast_24h),
                "forecast": forecast_24h,
                "total_power_sum_raw": round(total_wh, 1),
                "updated_at": datetime.now(ZoneInfo(TIMEZONE)).isoformat(),
                "source": "open-meteo-solar-forecast",
            },
        )

        log.info(
            f"solar_forecast_tomorrow: {len(forecast_24h)} points mis à jour pour demain"
        )

    except Exception as err:
        log.error(f"solar_forecast_tomorrow failed: {err}")
