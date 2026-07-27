from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from open_meteo_solar_forecast import OpenMeteoSolarForecast

TIMEZONE = "Europe/Zurich"

LATITUDE = 46.524288
LONGITUDE = 6.906411
DECLINATION = 30, 30
AZIMUTH = 34, -146
DC_KWP = 8.550, 4.500

ENTITY_ID = "sensor.solar_forecast_24h_fixed"


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
        return await forecast.estimate()


def _build_forecast_24h(estimate, tz):
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()
    hourly_sum = {}
    hourly_count = {}

    for dt_obj, watt_value in estimate.watts.items():
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

    forecast = []
    total_power = 0.0

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

        power = round(power, 1)
        total_power = total_power + power

        forecast.append(
            {
                "datetime": dt_hour.isoformat(),
                "hour": hour,
                "power": power,
            }
        )

    return forecast, round(total_power, 1)


@time_trigger("cron(0 22 * * *)")
@time_trigger("startup")
async def update_solar_forecast_24h_fixed():
    try:
        tz = ZoneInfo(TIMEZONE)
        estimate = await _get_estimate()
        forecast_24h, total_power = _build_forecast_24h(estimate, tz)

        state.set(
            ENTITY_ID,
            value=total_power,
            new_attributes={
                "friendly_name": "Prévision solaire 24h figée",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "forecast": forecast_24h,
                "forecast_day": (datetime.now(tz) + timedelta(days=1)).date().isoformat(),
                "updated_at": datetime.now(tz).isoformat(),
                "source": "open-meteo-solar-forecast",
                "points_count": len(forecast_24h),
            },
        )

        log.info("solar_forecast_24h_fixed updated successfully")

    except Exception as err:
        log.error(f"solar_forecast_24h_fixed failed: {err}")
