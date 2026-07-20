import aiohttp

BASE = "https://eu5.fusionsolar.huawei.com"
FLOW_BASE = "https://uni004eu5.fusionsolar.huawei.com"
STATION = "NE=152120280"


def get_user():
    user = pyscript.config.get("fusionsolar_user", "")
    if not user:
        raise RuntimeError("fusionsolar_user absent")
    return user


def get_password():
    password = pyscript.config.get("fusionsolar_password", "")
    if not password:
        raise RuntimeError("fusionsolar_password absent")
    return password


@service
async def fusionsolar_login_test():
    log.info("[FusionSolar] service fusionsolar_login_test called")
    state.set("sensor.fs_login_test", value="started")

    user = get_user()
    password = get_password()

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        login_url = BASE + "/thirdData/login"
        body = {
            "userName": user,
            "systemCode": password,
        }

        log.info(f"[FusionSolar] login POST {login_url}")
        async with session.post(login_url, json=body, timeout=30, allow_redirects=True) as resp:
            login_text = await resp.text()
            log.info(f"[FusionSolar] login status={resp.status}")
            log.info(f"[FusionSolar] login final_url={resp.url}")
            log.info(f"[FusionSolar] login content_type={resp.headers.get('Content-Type', '')}")
            log.info(f"[FusionSolar] login body_head={login_text[:300]}")

        jar = session.cookie_jar.filter_cookies(BASE)
        cookies = {k: v.value for k, v in jar.items()}
        log.info(f"[FusionSolar] cookies reçus={list(cookies.keys())}")

        flow_url = FLOW_BASE + "/rest/pvms/web/station/v3/overview/energy-flow"
        params = {
            "stationDn": STATION,
            "featureId": "aifc",
        }

        log.info(f"[FusionSolar] flow GET {flow_url} params={params}")
        async with session.get(flow_url, params=params, timeout=30, allow_redirects=True) as resp:
            flow_text = await resp.text()
            flow_status = resp.status
            flow_final_url = str(resp.url)
            flow_content_type = resp.headers.get("Content-Type", "")

            log.info(f"[FusionSolar] flow status={flow_status}")
            log.info(f"[FusionSolar] flow final_url={flow_final_url}")
            log.info(f"[FusionSolar] flow content_type={flow_content_type}")
            log.info(f"[FusionSolar] flow body_head={flow_text[:500]}")

            if "application/json" in flow_content_type:
                try:
                    data = await resp.json()
                    has_data = "data" in data

                    state.set(
                        "sensor.fs_login_test",
                        value="ok",
                        new_attributes={
                            "login_status": "ok",
                            "flow_status": flow_status,
                            "flow_url": flow_final_url,
                            "cookie_names": list(cookies.keys()),
                            "has_data": has_data,
                        },
                    )

                    persistent_notification.create(
                        title="FusionSolar login test",
                        message=(
                            "Succès du test de login direct.\n\n"
                            f"Login URL finale: {resp.url}\n"
                            f"Flow status: {flow_status}\n"
                            f"Flow URL: {flow_final_url}\n"
                            f"Cookies: {', '.join(cookies.keys()) or 'aucun'}\n"
                            f"Champ 'data' présent: {has_data}"
                        ),
                        notification_id="fusionsolar_login_test",
                    )

                    log.info("[FusionSolar] direct login test OK")
                except Exception as e:
                    state.set(
                        "sensor.fs_login_test",
                        value="json_error",
                        new_attributes={
                            "error": str(e),
                            "flow_status": flow_status,
                            "flow_url": flow_final_url,
                            "cookie_names": list(cookies.keys()),
                        },
                    )
                    log.error(f"[FusionSolar] json decode failed: {e}")
            else:
                state.set(
                    "sensor.fs_login_test",
                    value="not_json",
                    new_attributes={
                        "flow_status": flow_status,
                        "flow_url": flow_final_url,
                        "content_type": flow_content_type,
                        "cookie_names": list(cookies.keys()),
                        "body_head": flow_text[:300],
                    },
                )
                log.warning("[FusionSolar] flow did not return JSON")
