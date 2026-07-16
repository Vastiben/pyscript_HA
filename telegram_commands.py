"""
/config/pyscript/telegram_commands.py

Generic Telegram command router for Home Assistant pyscript.

Goal:
- Keep Telegram command handling in ONE reusable pyscript file.
- Let application-specific scripts, such as fusionsolar.py, react to clean internal events.
- Avoid a dangerous generic "write any file" command.

Supported commands out of the box:
  /tg_help
  /fs_cookie <full Cookie header value>
  /fs_roarand <Roarand header value>
  /fs_status
  /fs_test
  /fs_reset

How it works:
- /fs_cookie and /fs_roarand write only whitelisted files.
- /fs_status, /fs_test, /fs_reset fire a safe internal Home Assistant event:
    fusionsolar_command
  that is handled by /config/pyscript/fusionsolar.py.

To add future apps:
- Add entries in COMMANDS below.
- For app actions, fire a dedicated event like "myapp_command".
"""

from pathlib import Path
from datetime import datetime

# =========================
# USER CONFIGURATION
# =========================
CONFIG = {
    # Telegram notify service used to answer commands.
    # Example service notify.telegram -> domain="notify", service="telegram"
    # Example service notify.bastien -> domain="notify", service="bastien"
    "telegram_domain": "notify",
    "telegram_service": "telegram",

    # Recommended: restrict commands to your Telegram chat_id.
    # If empty, commands are accepted from any chat that Home Assistant telegram_bot allows.
    # Example: [123456789]
    "allowed_chat_ids": [],

    # Optional: when True, unknown commands starting with /tg or /fs get a help answer.
    "answer_unknown_known_prefixes": True,
}

# =========================
# SAFE COMMAND REGISTRY
# =========================
COMMANDS = {
    "/tg_help": {
        "type": "help",
        "description": "Afficher les commandes gérées par pyscript",
    },

    # FusionSolar file updates
    "/fs_cookie": {
        "type": "write_file",
        "description": "Enregistrer le cookie FusionSolar",
        "path": "/config/fusionsolar/cookie.txt",
        "secret": True,
        "min_length": 20,
        "must_contain": "=",
        "success": "✅ Cookie FusionSolar enregistré. Lance /fs_test pour vérifier.",
    },
    "/fs_roarand": {
        "type": "write_file",
        "description": "Enregistrer le header Roarand FusionSolar",
        "path": "/config/fusionsolar/roarand.txt",
        "secret": True,
        "min_length": 0,
        "must_contain": None,
        "success": "✅ Roarand FusionSolar enregistré. Lance /fs_test pour vérifier.",
    },

    # FusionSolar app actions. The FusionSolar script listens to fusionsolar_command.
    "/fs_status": {
        "type": "fire_event",
        "description": "Afficher l'état FusionSolar",
        "event_type": "fusionsolar_command",
        "event_data": {"action": "status"},
    },
    "/fs_test": {
        "type": "fire_event",
        "description": "Tester FusionSolar immédiatement",
        "event_type": "fusionsolar_command",
        "event_data": {"action": "test"},
    },
    "/fs_reset": {
        "type": "fire_event",
        "description": "Supprimer cookie et Roarand FusionSolar",
        "event_type": "fusionsolar_command",
        "event_data": {"action": "reset"},
    },
}

# Hard safety guard: only these files may be written by write_file commands.
ALLOWED_WRITE_PATHS = {
    "/config/fusionsolar/cookie.txt",
    "/config/fusionsolar/roarand.txt",
}


def _chat_allowed(chat_id):
    allowed = CONFIG.get("allowed_chat_ids") or []
    if not allowed:
        return True
    try:
        return int(chat_id) in [int(x) for x in allowed]
    except Exception:
        return False


def _notify(message, target=None):
    kwargs = {"message": message}
    if target is not None:
        kwargs["target"] = target
    service.call(CONFIG["telegram_domain"], CONFIG["telegram_service"], **kwargs)


def _event_chat_id(**kwargs):
    # HA telegram_command normally contains chat_id. Keep fallbacks for variants.
    return kwargs.get("chat_id") or kwargs.get("user_id") or kwargs.get("from_id")


def _event_command(**kwargs):
    return str(kwargs.get("command") or "").strip()


def _event_text(**kwargs):
    # telegram_command args can be a list or a string depending on HA setup.
    args = kwargs.get("args", "")
    if isinstance(args, list):
        return " ".join(str(x) for x in args).strip()
    return str(args or "").strip()


def _safe_write(path, content):
    path = str(Path(path))
    if path not in ALLOWED_WRITE_PATHS:
        raise RuntimeError(f"Write path not allowed: {path}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip(), encoding="utf-8")
    return path


def _help_text():
    lines = ["🤖 Commandes pyscript disponibles", ""]
    for command, spec in sorted(COMMANDS.items()):
        desc = spec.get("description", "")
        lines.append(f"{command} — {desc}")
    lines.append("")
    lines.append("Exemples :")
    lines.append("/fs_cookie SESSION=...; other=value...")
    lines.append("/fs_test")
    return "\n".join(lines)


def _execute_write_file(command, spec, text, chat_id):
    min_length = spec.get("min_length", 0)
    must_contain = spec.get("must_contain")
    if len(text) < min_length:
        _notify(f"❌ {command}: contenu trop court ou absent.", target=chat_id)
        return
    if must_contain and must_contain not in text:
        _notify(f"❌ {command}: contenu invalide, je ne vois pas '{must_contain}'.", target=chat_id)
        return
    path = _safe_write(spec["path"], text)
    _notify(spec.get("success", f"✅ Fichier écrit: {path}"), target=chat_id)


def _execute_fire_event(spec, text, chat_id):
    data = dict(spec.get("event_data", {}))
    data["chat_id"] = chat_id
    data["text"] = text
    data["source"] = "telegram_commands.py"
    data["ts"] = datetime.now().isoformat()
    event.fire(spec["event_type"], **data)


@event_trigger("telegram_command")
def telegram_command_router(**kwargs):
    chat_id = _event_chat_id(**kwargs)
    command = _event_command(**kwargs)
    text = _event_text(**kwargs)

    if not command:
        return
    if not _chat_allowed(chat_id):
        return

    spec = COMMANDS.get(command)
    if not spec:
        if CONFIG.get("answer_unknown_known_prefixes", True) and (command.startswith("/tg") or command.startswith("/fs")):
            _notify("❌ Commande inconnue.\n\n" + _help_text(), target=chat_id)
        return

    ctype = spec.get("type")
    try:
        if ctype == "help":
            _notify(_help_text(), target=chat_id)
        elif ctype == "write_file":
            _execute_write_file(command, spec, text, chat_id)
        elif ctype == "fire_event":
            _execute_fire_event(spec, text, chat_id)
        else:
            _notify(f"❌ Type de commande non supporté: {ctype}", target=chat_id)
    except Exception as exc:
        _notify(f"❌ Erreur commande {command}\n{exc}", target=chat_id)
        log.error(f"Telegram command {command} failed: {exc}")
