from datetime import datetime
from pathlib import Path


# --- CONFIG ---

GITHUB_OWNER = "Vastiben"
GITHUB_REPO = "pyscript_HA"
GITHUB_PATH = "logs/ha_warnings_errors.log"
GITHUB_TOKEN = pyscript.config.get("github_token", "")
LOCAL_LOG_FILE = "/config/pyscript/logs/ha_warnings_errors.log"


def _notify(msg, chat_id=None):
    """Envoie un message Telegram en HTML pour eviter les erreurs d'entites."""
    if not chat_id:
        return
    service.call(
        "telegram_bot",
        "send_message",
        target=chat_id,
        message=str(msg),
        parse_mode="html",
        disable_web_page_preview=True,
    )


def _format_source(source):
    if isinstance(source, (list, tuple)) and len(source) >= 2:
        return f"{source[0]}:{source[1]}"
    return str(source)


def _collect_log_entries():
    try:
        records = hass.data["system_log"].records
    except Exception as e:
        log.error("GitHub logs: impossible de lire system_log: %s", str(e))
        return ""

    lines = []
    for key, entry in records.items():
        level = getattr(entry, "level", "?")
        name = getattr(entry, "name", "")
        messages = getattr(entry, "message", [])
        timestamp = getattr(entry, "timestamp", 0)
        source = getattr(entry, "source", ("", ""))
        count = getattr(entry, "count", 1)

        try:
            ts = datetime.fromtimestamp(float(timestamp)).isoformat()
        except Exception:
            ts = str(timestamp)

        msg = messages[0] if messages else ""
        src = _format_source(source)

        lines.append(
            "[" + ts + "] "
            + str(level).ljust(8)
            + " (" + name + ") "
            + msg
            + "  [src=" + src + ", count=" + str(count) + "]"
        )

    if not lines:
        return ""

    header = (
        "Snapshot "
        + datetime.now().isoformat()
        + " -- "
        + str(len(lines))
        + " entree(s) system_log\n\n"
    )
    return header + "\n".join(lines) + "\n"


@pyscript_compile
def _write_local_log_native(path, text):
    from pathlib import Path as _Path
    _Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@pyscript_compile
def _push_to_github_native(text, owner, repo, path, token):
    """Pousse vers GitHub via urllib.request (pas de requests/urllib3)."""
    import base64 as _b64
    import json as _json
    import urllib.request as _url
    import urllib.error as _uerr
    from datetime import datetime as _dt

    if not token:
        raise RuntimeError("GITHUB_TOKEN manquant")

    base_url = (
        "https://api.github.com/repos/"
        + owner + "/" + repo + "/contents/" + path
    )
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "pyscript-ha",
    }

    sha = None
    req = _url.Request(base_url, headers=headers, method="GET")
    try:
        with _url.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")
    except _uerr.HTTPError as e:
        if e.code != 404:
            raise

    content_b64 = _b64.b64encode(text.encode("utf-8")).decode("ascii")
    payload = {
        "message": "HA logs system_log " + _dt.now().isoformat(),
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    body = _json.dumps(payload).encode("utf-8")
    req = _url.Request(base_url, data=body, headers=headers, method="PUT")
    with _url.urlopen(req, timeout=30) as resp:
        result = _json.loads(resp.read().decode("utf-8"))
        return result.get("commit", {}).get("html_url", "")


@event_trigger("pyscript_ghpush")
def handle_pyscript_ghpush(action=None, chat_id=None, **kwargs):
    if action != "push":
        return

    text = _collect_log_entries()

    if not text.strip():
        log.debug("GitHub logs: aucune entree system_log.")
        _notify("Aucune entree a envoyer.", chat_id)
        return

    try:
        task.executor(_write_local_log_native, LOCAL_LOG_FILE, text)
    except Exception as e:
        log.error("GitHub logs: erreur ecriture locale: %s", str(e))

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
            log.info("GitHub logs: push OK -> %s", commit_url)
            _notify("Logs pousses ! <a href=\"" + commit_url + "\">voir commit</a>", chat_id)
        else:
            _notify("Logs pousses sur GitHub.", chat_id)
    except Exception as e:
        log.error("GitHub logs: push FAIL: %s", str(e))
        _notify("Erreur push: " + str(e)[:300], chat_id)
