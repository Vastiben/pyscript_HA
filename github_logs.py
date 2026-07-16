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
    """
    Lit les entrées WARNING/ERROR directement depuis hass.data['system_log'].
    Disponible sans fichier depuis HA 2025.11.
    Retourne une chaîne de texte formatée.
    """
    try:
        records = hass.data["system_log"].records
    except Exception as e:
        log.error(f"GitHub logs: impossible de lire system_log: {e}")
        return ""

    lines = []
    for key, entry in records.items():
        level     = getattr(entry, 'level', '?')
        name      = getattr(entry, 'name', '')
        messages  = getattr(entry, 'message', [])
        timestamp = getattr(entry, 'timestamp', 0)
        source    = getattr(entry, 'source', ('', ''))
        count     = getattr(entry, 'count', 1)

        try:
            ts = datetime.fromtimestamp(float(timestamp)).isoformat()
        except Exception:
            ts = str(timestamp)

        msg = messages[0] if messages else ''
        src = f"{source[0]}:{source[1]}" if isinstance(source, (list, tuple)) and len(source) >= 2 else str(source)

        lines.append(
            f"[{ts}] {level:8s} ({name}) {msg}  "
            f"[src={src}, count={count}]"
        )

    if not lines:
        return ""

    header = f"Snapshot {datetime.now().isoformat()} — {len(lines)} entrée(s) WARNING/ERROR\n\n"
    return header + "\n".join(lines) + "\n"


@pyscript_compile
def _write_local_log(text: str):
    """Fonction native : écrase le fichier local avec le contenu filtré."""
    from pathlib import Path
    Path("/config/pyscript/logs").mkdir(parents=True, exist_ok=True)
    with open("/config/pyscript/logs/ha_warnings_errors.log", "w", encoding="utf-8") as f:
        f.write(text)


def _get_remote_sha():
    """Récupère la SHA du fichier distant s'il existe, sinon None."""
    if not GITHUB_TOKEN:
        log.error("GitHub logs: GITHUB_TOKEN manquant (pyscript.config['github_token'])")
        return None
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    r = requests.get(url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
    if r.status_code == 404:
        return None
    try:
        r.raise_for_status()
        return r.json().get("sha")
    except Exception as e:
        log.error(f"GitHub logs: GET sha échoué ({r.status_code}): {e}")
        return None


def _push_to_github(text: str):
    """Crée / met à jour le fichier sur GitHub via l'API contents."""
    if not GITHUB_TOKEN:
        log.error("GitHub logs: GITHUB_TOKEN manquant")
        return
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    content_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    sha = _get_remote_sha()
    payload = {
        "message": f"HA logs WARNING/ERROR {datetime.now().isoformat()}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, json=payload, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
    try:
        r.raise_for_status()
        commit_url = r.json().get("commit", {}).get("html_url", "")
        log.info(f"GitHub logs: push OK → {commit_url}")
    except Exception as e:
        log.error(f"GitHub logs: push FAIL ({r.status_code}): {e} — {r.text}")


@time_trigger("period(now, 1min)")
def push_ha_warning_error_logs():
    """Toutes les minutes : lit system_log, écrit localement, pousse vers GitHub."""
    text = _collect_log_entries()

    if not text.strip():
        log.debug("GitHub logs: aucune entrée WARNING/ERROR.")
        return

    # 1) Ecriture locale (I/O natif via pyscript_compile)
    task.executor(_write_local_log, text)

    # 2) Push GitHub (requests dans un thread séparé)
    task.executor(_push_to_github, text)
