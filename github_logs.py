from datetime import datetime
import base64
import requests
from pathlib import Path

# --- CONFIG ---

GITHUB_OWNER   = "Vastiben"
GITHUB_REPO    = "pyscript_HA"
GITHUB_PATH    = "logs/ha_warnings_errors.log"
GITHUB_TOKEN   = pyscript.config.get("github_token", "")
LOG_FILE       = "/config/home-assistant.log"
LOCAL_LOG_FILE = "/config/pyscript/logs/ha_warnings_errors.log"


@pyscript_compile
def _collect_and_write_logs_native():
    """
    Fonction native (hors sandbox pyscript) : open() est autorisé ici.
    Lit le log HA, filtre WARNING/ERROR, écrase le fichier local, retourne le texte.
    """
    from datetime import datetime
    from pathlib import Path

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        raise RuntimeError(f"Impossible de lire {LOG_FILE}: {e}") from e

    filtered = [l for l in lines if "WARNING" in l or "ERROR" in l]
    header = f"Snapshot {datetime.now().isoformat()} — WARNING/ERROR uniquement\n\n"
    text = header + "".join(filtered)

    Path(LOCAL_LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    return text


def _get_remote_sha():
    """Récupère la SHA du fichier distant s'il existe, sinon None."""
    if not GITHUB_TOKEN:
        log.error("GitHub logs: GITHUB_TOKEN manquant (pyscript.config['github_token'])")
        return None

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return None
    try:
        r.raise_for_status()
    except Exception as e:
        log.error(f"GitHub logs: GET contents a échoué ({r.status_code}): {e} — {r.text}")
        return None
    return r.json().get("sha")


def _push_to_github(text: str):
    """Crée / met à jour le fichier sur GitHub via l'API contents."""
    if not GITHUB_TOKEN:
        log.error("GitHub logs: GITHUB_TOKEN manquant (pyscript.config['github_token'])")
        return

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    content_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    sha = _get_remote_sha()

    payload = {
        "message": f"HA logs WARNING/ERROR {datetime.now().isoformat()}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, json=payload, headers=headers)
    try:
        r.raise_for_status()
        commit_url = r.json().get("commit", {}).get("html_url")
        log.info(f"GitHub logs: push OK → {commit_url}")
    except Exception as e:
        log.error(f"GitHub logs: push FAIL ({r.status_code}): {e} — {r.text}")


@time_trigger("period(now, 1min)")
def push_ha_warning_error_logs():
    """Toutes les minutes : collecte/écrit les logs filtrés, puis pousse vers GitHub."""
    try:
        text = task.executor(_collect_and_write_logs_native)
    except Exception as e:
        log.error(f"GitHub logs: erreur collect/write: {e}")
        return

    if not text or not text.strip():
        log.debug("GitHub logs: aucun WARNING/ERROR, pas de push.")
        return

    task.executor(_push_to_github, text)
