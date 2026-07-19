"""
🔹 Telegram Command Router (générique)
🔹 Centralise toutes les commandes
🔹 Envoie des events vers les apps (FusionSolar, etc.)

Architecture:
Telegram → telegram_commands → event → app

Logs: [TG]
"""

from datetime import datetime

SECRETS_PATH = "/config/secrets.yaml"

CONFIG = {
    "allowed_chat_ids": [],  # optionnel sécurité
    "debug": True,
}


# =========================
# DEBUG
# =========================
def dbg(msg):
    if CONFIG["debug"]:
        log.info(f"[TG] {msg}")


dbg("✅ telegram_commands.py chargé")

HELP_TEXT = (
    "🤖 Commandes disponibles :\n\n"
    "📊 FusionSolar\n"
    "/fscookie — mettre à jour le cookie\n"
    "/fsroarand — mettre à jour le roarand\n"
    "/fsstatus — statut\n"
    "/fshealth — diagnostic complet\n"
    "/fstest — test\n"
    "/fsreset — reset\n\n"
    "🔧 GitHub / Pyscript\n"
    "/ghpull — récupérer le dernier code GitHub\n"
    "/ghpush — pousser les logs HA vers GitHub\n\n"
    "ℹ️ Aide\n"
    "/help ou /h — afficher ce message"
)


# =========================
# COMMANDES
# =========================
COMMANDS = {
    "/help": {"type": "help"},
    "/h":    {"type": "help"},

    "/fshealth": {
        "type": "event",
        "action": "health",
    },

    "/fscookie": {
        "type": "secrets_write",
        "key": "fusionsolar_cookie",
        "min": 20,
    },

    "/fsroarand": {
        "type": "secrets_write",
        "key": "fusionsolar_roarand",
    },

    "/fsstatus": {"type": "event", "action": "status"},
    "/fstest":   {"type": "event", "action": "test"},
    "/fsreset":  {"type": "event", "action": "reset"},

    # === GitHub / Pyscript ===
    "/ghpull": {
        "type": "event",
        "event": "pyscript_ghpull",
        "action": "pull",
    },
    "/ghpush": {
        "type": "event",
        "event": "pyscript_ghpush",
        "action": "push",
    },
}

ALLOWED_SECRETS_KEYS = {
    "fusionsolar_cookie",
    "fusionsolar_roarand",
}


# =========================
# HELPERS
# =========================
def notify(msg, chat_id=None):
    dbg(f"Notify → {msg[:50]}")
    data = {"message": msg}
    if chat_id:
        data["target"] = chat_id
    service.call("telegram_bot", "send_message", **data)


def parse_args(args):
    """Convertit les args Telegram en string propre.

    Les args peuvent arriver comme une liste de tokens mixtes
    (strings, entiers…) ou comme une string brute.
    Utilise une boucle explicite : pyscript ne supporte pas
    les generator expressions (ast_generatorexp).
    """
    if isinstance(args, list):
        parts = []
        for x in args:
            parts.append(str(x))
        return " ".join(parts).strip()
    if args is None:
        return ""
    return str(args).strip()


@pyscript_compile
def _write_secret_native(secrets_path, key, value):
    """Met à jour UNE clé dans secrets.yaml sans toucher aux autres."""
    import yaml as _yaml
    from pathlib import Path as _Path

    path = _Path(secrets_path)

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
    else:
        data = {}

    data[key] = value

    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


# =========================
# ROUTER
# =========================
@event_trigger("telegram_command")
def router(**kwargs):
    """Route les commandes Telegram vers les bons handlers."""
    dbg(f"RAW: {kwargs}")

    cmd = (
        (kwargs.get("command") or "")
        .lower()
        .replace("_", "")
        .replace("-", "")
    )
    text = parse_args(kwargs.get("args"))
    chat = kwargs.get("chat_id")

    dbg(f"CMD={cmd} TEXT_LEN={len(text)}")

    spec = COMMANDS.get(cmd)

    if not spec:
        notify("❌ Commande inconnue. Tape /help pour la liste.", chat)
        return

    # =====================
    # HELP
    # =====================
    if spec["type"] == "help":
        notify(HELP_TEXT, chat)

    # =====================
    # SECRETS WRITE
    # =====================
    elif spec["type"] == "secrets_write":

        if len(text) < spec.get("min", 0):
            notify("❌ Contenu trop court.", chat)
            return

        key = spec["key"]

        if key not in ALLOWED_SECRETS_KEYS:
            notify("❌ Accès interdit.", chat)
            return

        try:
            task.executor(
                _write_secret_native, SECRETS_PATH, key, text.strip()
            )
            dbg(f"secrets.yaml mis à jour: {key}")
            notify("✅ Enregistré dans secrets.yaml.", chat)
        except Exception as e:
            notify(f"❌ Erreur écriture secrets.yaml: {e}", chat)

    # =====================
    # EVENT
    # =====================
    elif spec["type"] == "event":

        event_name = spec.get("event", "fusionsolar_command")
        dbg(f"Fire event → {event_name}:{spec['action']}")

        event.fire(
            event_name,
            action=spec["action"],
            chat_id=chat,
            text=text,
            ts=datetime.now().isoformat(),
        )
