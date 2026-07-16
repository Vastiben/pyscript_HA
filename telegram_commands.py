"""
/config/pyscript/telegram_commands.py

Generic Telegram command router for Home Assistant pyscript, with verbose debug logs.

Commands:
  /tg_help
  /fs_cookie <full Cookie header value>
  /fs_roarand <Roarand header value>
  /fs_status
  /fs_test
  /fs_reset

Debug logs are prefixed with [TG_ROUTER].
Set DEBUG=False once everything works.
"""

from pathlib import Path
from datetime import datetime

DEBUG = True

CONFIG = {
    "telegram_domain": "notify",
    "telegram_service": "telegram",
    "allowed_chat_ids": [],
    "answer_unknown_known_prefixes": True,
}

COMMANDS = {
    "/tg_help": {
        "type": "help",
        "description": "Afficher les commandes gérées par pyscript",
    },
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

ALLOWED_WRITE_PATHS = {
    "/config/fusionsolar/cookie.txt",
    "/config/fusionsolar/roarand.txt",
}


def dbg(msg):
    if DEBUG:
        log.info(f"[TG_ROUTER] {msg}")


dbg("telegram_commands.py chargé")


def _mask_secret(text):
    if text is None:
        return ""
    text = str(text)
    if len(text) <= 12:
        return "***"
    return text[:6] + "..." + text[-6:]


def _chat_allowed(chat_id):
    allowed = CONFIG.get("allowed_chat_ids") or []
    if not allowed:
        dbg(f"Chat autorisé car allowed_chat_ids est vide: chat_id={chat_id}")
        return True
    try:
        result = int(chat_id) in [int(x) for x in allowed]
        dbg(f"Vérification chat_id={chat_id}, autorisé={result}")
        return result
    except Exception as exc:
        dbg(f"Erreur vérification chat_id={chat_id}: {exc}")
        return False


def _notify(message, target=None):
    dbg(f"Notification Telegram: target={target}, message_length={len(str(message))}")
    kwargs = {"message": message}
    if target is not None:
        kwargs["target"] = target
    service.call(CONFIG["telegram_domain"], CONFIG["telegram_service"], **kwargs)


def _event_chat_id(**kwargs):
    return kwargs.get("chat_id") or kwargs.get("user_id") or kwargs.get("from_id")


def _event_command(**kwargs):
    return str(kwargs.get("command") or "").strip()


def _event_text(**kwargs):
    args = kwargs.get("args", "")
    if isinstance(args, list):
        return " ".join(str(x) for x in args).strip()
    return str(args or "").strip()


def _safe_write(path, content):
    path = str(Path(path))
    dbg(f"Demande écriture fichier: path={path}, content_length={len(content)}")
    if path not in ALLOWED_WRITE_PATHS:
        dbg(f"Écriture refusée: path non autorisé: {path}")
        raise RuntimeError(f"Write path not allowed: {path}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip(), encoding="utf-8")
    dbg(f"Fichier écrit avec succès: {path}, bytes={len(content.strip().encode('utf-8'))}")
    return path


def _help_text():
    lines = ["🤖 Commandes pyscript disponibles", ""]
    for command, spec in sorted(COMMANDS.items()):
        lines.append(f"{command} — {spec.get('description', '')}")
    lines.append("")
    lines.append("Exemples :")
    lines.append("/fs_cookie SESSION=...; other=value...")
    lines.append("/fs_test")
    return "\n".join(lines)


def _execute_write_file(command, spec, text, chat_id):
    dbg(
        f"Execute write_file: command={command}, path={spec.get('path')}, "
        f"text_length={len(text)}, secret={spec.get('secret', False)}"
    )
    min_length = spec.get("min_length", 0)
    must_contain = spec.get("must_contain")

    if len(text) < min_length:
        dbg(f"Validation échouée: contenu trop court pour {command}")
        _notify(f"❌ {command}: contenu trop court ou absent.", target=chat_id)
        return

    if must_contain and must_contain not in text:
        dbg(f"Validation échouée: '{must_contain}' absent pour {command}")
        _notify(f"❌ {command}: contenu invalide, je ne vois pas '{must_contain}'.", target=chat_id)
        return

    if spec.get("secret", False):
        dbg(f"Secret reçu pour {command}: {_mask_secret(text)}")
    else:
        dbg(f"Contenu reçu pour {command}: {text}")

    path = _safe_write(spec["path"], text)
    _notify(spec.get("success", f"✅ Fichier écrit: {path}"), target=chat_id)


def _execute_fire_event(spec, text, chat_id):
    data = dict(spec.get("event_data", {}))
    data["chat_id"] = chat_id
    data["text"] = text
    data["source"] = "telegram_commands.py"
    data["ts"] = datetime.now().isoformat()
    dbg(f"Fire event: event_type={spec['event_type']}, data={data}")
    event.fire(spec["event_type"], **data)


@event_trigger("telegram_command")
def telegram_command_router(**kwargs):
    dbg(f"Event telegram_command reçu: {kwargs}")

    chat_id = _event_chat_id(**kwargs)
    command = _event_command(**kwargs)
    text = _event_text(**kwargs)

    dbg(f"Parsed event: chat_id={chat_id}, command={command}, text_length={len(text)}")

    if not command:
        dbg("Commande vide, arrêt")
        return

    if not _chat_allowed(chat_id):
        dbg(f"Chat refusé: chat_id={chat_id}, command={command}")
        return

    spec = COMMANDS.get(command)
    if not spec:
        dbg(f"Commande inconnue: {command}")
        if CONFIG.get("answer_unknown_known_prefixes", True) and (command.startswith("/tg") or command.startswith("/fs")):
            _notify("❌ Commande inconnue.\n\n" + _help_text(), target=chat_id)
        return

    ctype = spec.get("type")
    dbg(f"Commande reconnue: command={command}, type={ctype}")

    try:
        if ctype == "help":
            dbg("Exécution help")
            _notify(_help_text(), target=chat_id)
        elif ctype == "write_file":
            _execute_write_file(command, spec, text, chat_id)
        elif ctype == "fire_event":
            _execute_fire_event(spec, text, chat_id)
        else:
            dbg(f"Type de commande non supporté: {ctype}")
            _notify(f"❌ Type de commande non supporté: {ctype}", target=chat_id)
    except Exception as exc:
        dbg(f"Erreur commande {command}: {exc}")
        _notify(f"❌ Erreur commande {command}\n{exc}", target=chat_id)
        log.error(f"[TG_ROUTER] Telegram command {command} failed: {exc}")
