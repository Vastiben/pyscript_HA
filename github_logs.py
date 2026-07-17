from datetime import datetime
from pathlib import Path

# --- CONFIG ---

GITHUB_OWNER   = "Vastiben"
GITHUB_REPO    = "pyscript_HA"
GITHUB_PATH    = "logs/ha_warnings_errors.log"
GITHUB_TOKEN   = pyscript.config.get("github_token", "")
LOCAL_LOG_FILE = "/config/pyscript/logs/ha_warnings_errors.log"


def _notify(msg, chat_id=None):
    data = {"message": msg}
    if chat_id:
        data["target"] = chat_id
    service.call("telegram_bot", "send_message", **data)


def _collect_log_entries():
    try:
        records = hass.data["system_log"].records
    except Exception as e:
        log.error("GitHub logs: impossible de lire system_log: " + str(e))
        return ""

    lines = []
    for key, entry in records.items():
        level     = getattr(entry, "level", "?")
        name      = getattr(entry, "name", "")
        messages  = getattr(entry, "message", [])
        timestamp = getattr(entry, "timestamp", 0)
        source    = getattr(entry, "source", ("", ""))
        count     = getattr(entry, "count", 1)

        try:
            ts = datetime.fromtimestamp(float(timestamp)).isoformat()
        except Exception:
            ts = str(timestamp)

        msg = messages[0] if messages else ""
        src = (
            source[0] + ":" + str(source[1])
            if isinstance(source, (list, tuple)) and len(source) >= 2
            else str(source)
        )
        lines.append("[" + ts + "] " + str(level).ljust(8) + " (" + name + ") " + msg + "  [src=" + src + ", count=" + str(count) + "]")

    if not lines:
        return ""

    header = "Snapshot " + datetime.now().isoformat() + " -- " + str(len(lines)) + " entree(s) system_log\n\n"
    return header + "\n".join(lines) + "\n"


@pyscript_compile
def _write_local_log_native(path, text):
    from pathlib import Path as _Path
    _Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@pyscript_compile
def _push_to_github_native(text, owner, repo, path, token):
    import base64 as _b64
    import requests as _req
    from datetime import datetime as _dt

    if not token:
        raise RuntimeError("GITHUB_TOKEN manquant")

    base_url = "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path
    headers  = {"Authorization": "Bearer " + token}

    r = _req.get(base_url, headers=headers)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")
    elif r.status_code != 404:
        r.raise_for_status()

    content_b64 = _b64.b64encode(text.encode("utf-8")).decode("ascii")
    payload = {
        "message": "HA logs system_log " + _dt.now().isoformat(),
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    r = _req.put(base_url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json().get("commit", {}).get("html_url", "")


def push_ha_warning_error_logs(chat_id=None):
    text = _collect_log_entries()

    if not text.strip():
        log.debug("GitHub logs: aucune entree system_log.")
        _notify("Aucune entree a envoyer.", chat_id)
        return

    try:
        task.executor(_write_local_log_native, LOCAL_LOG_FILE, text)
    except Exception as e:
        log.error("GitHub logs: erreur ecriture locale: " + str(e))

    try:
        commit_url = task.executor(
            _push_to_github_native,
            text,
            GITHUB_OWNER,
            GITHUB_REPO,
            GITHUB_PATH,
            GITHUB_TOKEN,
        )
        if commit_url:
            log.info("GitHub logs: push OK -> " + commit_url)
            _notify("Logs pousses sur GitHub !\n" + commit_url, chat_id)
        else:
            _notify("Logs pousses sur GitHub.", chat_id)
    except Exception as e:
        log.error("GitHub logs: push FAIL: " + str(e))
        _notify("Erreur ghpush :\n" + str(e), chat_id)


@event_trigger("pyscript_gh")
def handle_pyscript_gh(action=None, chat_id=None, **kwargs):
    if action == "push":
        push_ha_warning_error_logs(chat_id=chat_id)
