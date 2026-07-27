from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from open_meteo_solar_forecast import OpenMeteoSolarForecast

TIMEZONE = "Europe/Zurich"

LATITUDE = 46.46
LONGITUDE = 6.84
DECLINATION = 35
AZIMUTH = 180
DC_KWP = 9.6

SENSOR_PREFIX = "sensor.solar_forecast_tomorrow_h"
SUMMARY_SENSOR = "sensor.solar_forecast_tomorrow_summary"


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


async def _get_estimate():
    async with OpenMeteoSolarForecast(
        latitude=LATITUDE,
        longitude=LONGITUDE,
        declination=DECLINATION,
        azimuth=AZIMUTH,
        dc_kwp=DC_KWP,
    ) as forecast:
        estimate = await forecast.estimate()
    return estimate


def _build_hourly_forecast_from_watts(estimate, tz):
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()

    hourly_sum = {}
    hourly_count = {}

    watts_map = estimate.watts

    for dt_obj, watt_value in watts_map.items():
        if dt_obj is None:
            continue

        if dt_obj.tzinfo is None:
            dt_local = dt_obj.replace(tzinfo=tz)
        else:
            dt_local = dt_obj.astimezone(tz)

        if dt_local.date() != tomorrow:
            continue

        hour = dt_local.hour
        watt = _safe_float(watt_value, 0.0)

        if hour not in hourly_sum:
            hourly_sum[hour] = 0.0
            hourly_count[hour] = 0

        hourly_sum[hour] = hourly_sum[hour] + watt
        hourly_count[hour] = hourly_count[hour] + 1

    result = []

    for hour in range(24):
        dt_hour = datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            hour,
            0,
            0,
            tzinfo=tz,
        )

        power = 0.0
        if hour in hourly_sum and hourly_count[hour] > 0:
            power = hourly_sum[hour] / hourly_count[hour]

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
        tz = ZoneInfo(TIMEZONE)
        estimate = await _get_estimate()
        forecast_24h = _build_hourly_forecast_from_watts(estimate, tz)

        total_power = 0.0
        for item in forecast_24h:
            total_power = total_power + _safe_float(item["power"], 0.0)

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
                    "updated_at": datetime.now(tz).isoformat(),
                },
            )

        state.set(
            SUMMARY_SENSOR,
            value=round(total_power, 1),
            new_attributes={
                "friendly_name": "Prévision solaire demain résumé",
                "forecast_day": "tomorrow",
                "points_count": len(forecast_24h),
                "forecast": forecast_24h,
                "source": "open-meteo-solar-forecast",
                "updated_at": datetime.now(tz).isoformat(),
            },
        )

        log.info("solar_forecast_tomorrow updated successfully")

    except Exception as err:
        log.error(f"solar_forecast_tomorrow failed: {err}")
