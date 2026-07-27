from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import flatbuffers

from openmeteo_sdk.WeatherApiRequest import WeatherApiRequest
from openmeteo_sdk.WeatherApiResponse import WeatherApiResponse
from openmeteo_sdk.Variables import Variables

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


def _build_request_body():
    builder = flatbuffers.Builder(1024)

    timezone_str = builder.CreateString(TIMEZONE)

    WeatherApiRequest.StartWeatherApiRequest(builder)
    WeatherApiRequest.AddLatitude(builder, LATITUDE)
    WeatherApiRequest.AddLongitude(builder, LONGITUDE)
    WeatherApiRequest.AddHourly(builder, Variables().TEMPERATURE_2M)
    WeatherApiRequest.AddTimezone(builder, timezone_str)

    request_obj = WeatherApiRequest.EndWeatherApiRequest(builder)
    builder.Finish(request_obj)

    return bytes(builder.Output())


async def _get_temperature_response():
    body = _build_request_body()

    response = await task.executor(
        requests.post,
        "https://api.open-meteo.com/v1/forecast",
        data=body,
        headers={
            "Content-Type": "application/flatbuffers",
            "Accept": "application/flatbuffers",
        },
        timeout=30,
    )

    response.raise_for_status()
    data = response.content

    if not data:
        raise Exception("Empty response from Open-Meteo")

    return WeatherApiResponse.GetRootAsWeatherApiResponse(data, 0)


def _find_temperature_variable(hourly):
    for i in range(hourly.VariablesLength()):
        var = hourly.Variables(i)
        if var.Variable() == Variables().TEMPERATURE_2M:
            return var
    raise Exception("temperature_2m not found in hourly variables")


def _build_forecast_24h(weather_response, tz):
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()

    hourly = weather_response.Hourly()
    if hourly is None:
        raise Exception("Hourly section missing in response")

    temperature_var = _find_temperature_variable(hourly)

    start_ts = hourly.Time()
    end_ts = hourly.TimeEnd()
    interval_s = hourly.Interval()

    if interval_s <= 0:
        raise Exception("Invalid interval in hourly response")

    forecast = []
    total_temp = 0.0
    points_count = 0

    value_index = 0
    for ts in range(start_ts, end_ts, interval_s):
        dt_local = datetime.fromtimestamp(ts, tz=tz)

        if dt_local.date() == tomorrow:
            temperature = _safe_float(temperature_var.Values(value_index), 0.0)
            temperature = round(temperature, 1)

            forecast.append(
                {
                    "datetime": dt_local.isoformat(),
                    "hour": dt_local.hour,
                    "temperature": temperature,
                }
            )

            total_temp = total_temp + temperature
            points_count = points_count + 1

        value_index = value_index + 1

    if points_count == 0:
        raise Exception("No hourly temperature values found for tomorrow")

    average_temp = round(total_temp / points_count, 1)
    return forecast, average_temp


@time_trigger("cron(0 22 * * *)")
@time_trigger("startup")
async def update_temperature_forecast_24h_fixed():
    try:
        tz = ZoneInfo(TIMEZONE)
        weather_response = await _get_temperature_response()
        forecast_24h, average_temp = _build_forecast_24h(weather_response, tz)

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
                "source": "openmeteo_sdk",
                "points_count": len(forecast_24h),
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "timezone": TIMEZONE,
            },
        )

        log.info("temperature_forecast_24h_fixed updated successfully")

    except Exception as err:
        log.error(f"temperature_forecast_24h_fixed failed: {err}")
