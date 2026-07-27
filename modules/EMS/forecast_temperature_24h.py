from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import openmeteo_requests

TIMEZONE = "Europe/Zurich"

LATITUDE = 46.524288
LONGITUDE = 6.906411

ENTITY_ID = "sensor.temperature_forecast_24h_fixed"


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


async def _get_hourly_temperature():
    client = openmeteo_requests.AsyncClient()

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ["temperature_2m"],
        "timezone": TIMEZONE,
        "forecast_days": 2,
    }

    responses = await client.weather_api(
        "https://api.open-meteo.com/v1/forecast",
        params=params,
    )

    if not responses:
        raise Exception("No response returned by Open-Meteo")

    return responses[0]


def _build_temperature_forecast_24h(response, tz):
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()

    hourly = response.Hourly()
    if hourly is None:
        raise Exception("Hourly data missing in Open-Meteo response")

    start_ts = hourly.Time()
    end_ts = hourly.TimeEnd()
    interval_s = hourly.Interval()

    if interval_s <= 0:
        raise Exception("Invalid hourly interval returned by Open-Meteo")

    temperature_values = hourly.Variables(0).ValuesAsNumpy()

    forecast = []
    total_temp = 0.0
    point_count = 0

    for index, ts in enumerate(range(start_ts, end_ts, interval_s)):
        dt_local = datetime.fromtimestamp(ts, tz=tz)

        if dt_local.date() != tomorrow:
            continue

        temperature = _safe_float(temperature_values[index], 0.0)
        temperature = round(temperature, 1)

        forecast.append(
            {
                "datetime": dt_local.isoformat(),
                "hour": dt_local.hour,
                "temperature": temperature,
            }
        )

        total_temp = total_temp + temperature
        point_count = point_count + 1

    if len(forecast) != 24:
        log.warning(f"Expected 24 hourly points for tomorrow, got {len(forecast)}")

    average_temp = 0.0
    if point_count > 0:
        average_temp = round(total_temp / point_count, 1)

    return forecast, average_temp


@time_trigger("cron(0 22 * * *)")
@time_trigger("startup")
async def update_temperature_forecast_24h_fixed():
    try:
        tz = ZoneInfo(TIMEZONE)
        response = await _get_hourly_temperature()
        forecast_24h, average_temp = _build_temperature_forecast_24h(response, tz)

        state.set(
            ENTITY_ID,
            value=average_temp,
            new_attributes={
                "friendly_name": "Prévision température 24h figée",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
                "forecast": forecast_24h,
                "forecast_day": (datetime.now(tz) + timedelta(days=1)).date().isoformat(),
                "updated_at": datetime.now(tz).isoformat(),
                "source": "open-meteo",
                "points_count": len(forecast_24h),
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "timezone": TIMEZONE,
            },
        )

        log.info("temperature_forecast_24h_fixed updated successfully")

    except Exception as err:
        log.error(f"temperature_forecast_24h_fixed failed: {err}")
