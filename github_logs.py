from datetime import datetime
import base64
import requests
from pathlib import Path

# --- CONFIG ---

GITHUB_OWNER   = "Vastiben"
GITHUB_REPO    = "pyscript_HA"
GITHUB_PATH    = "logs/ha_warnings_errors.log"
GITHUB_TOKEN   = pyscript.config.get("github_token", "")
LOCAL_LOG_FILE = "/config/pyscript/logs/ha_warnings_errors.log"


def _collect_log_entries() -> str:
    """Lit les entrées system_log et renvoie un texte formaté."""
    try:
        records = hass.data["system_log"].records
    except Exception as e:
        log.error(f"GitHub logs: impossible de lire system_log: {e}")
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
            f"{source[0]}:{source[1]}"
            if isinstance(source, (list, tuple)) and len(source) >= 2
            else str(source)
        )

        lines.append(
            f"[{ts}] {level:8s} ({name}) {msg}  [src={src}, count={count}]"
        )

    if not lines:
        return ""

    header = (
        f"Snapshot {datetime.now().isoformat()} — "
        f"{len(lines)} entrée(s) system_log\n\n"
    )
    return header + "\n".join(lines) + "\n"


@pyscript_compile
def _write_local_log_native(text: str) -> None:
    """Fonction native : écrase le fichier local avec le contenu filtré."""
    Path(LOCAL_LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(text)


@pyscript_compile
def _push_to_github_native(text: str, owner: str, repo: str, path: str, token: str) -> str:
    """
    Fonction native : fait le PUT sur l'API GitHub et renvoie l'URL du commit.
    AUCUN appel à log / hass / APIs Pyscript ici, uniquement du Python standard.
    """
    import base64 as _b64
    import requests as _req

    if not token:
        raise RuntimeError("GITHUB_TOKEN manquant")

    base_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    # GET pour récupérer la SHA éventuelle (fichier déjà existant ou pas)
    headers = {"Authorization": f"Bearer {token}"}
    r = _req.get(base_url, headers=headers)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")
    elif r.status_code != 404:
        r.raise_for_status()

    content_b64 = _b64.b64encode(text.encode("utf-8")).decode("ascii")
    payload = {
        "message": f"HA logs system_log {datetime.now().isoformat()}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    r = _req.put(base_url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json().get("commit", {}).get("html_url", "")


@time_trigger("period(now, 1min)")
def push_ha_warning_error_logs():
    """Toutes les minutes : lit system_log, écrit localement, pousse vers GitHub."""
    text = _collect_log_entries()

    if not text.strip():
        log.debug("GitHub logs: aucune entrée system_log.")
        return

    # 1) Ecriture locale (I/O natif)
    try:
        task.executor(_write_local_log_native, text)
    except Exception as e:
        log.error(f"GitHub logs: erreur écriture fichier local: {e}")

    # 2) Push GitHub (requêtes HTTP en natif)
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
            log.info(f"GitHub logs: push OK → {commit_url}")
    except Exception as e:
        log.error(f"GitHub logs: push FAIL: {e}")
