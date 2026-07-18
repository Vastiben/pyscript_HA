---
name: homeassistant-pyscript
description: >
  Load when the user asks to create, modify, refactor or debug pyscript code
  for Home Assistant (main or backup) stored in the Vastiben GitHub repositories,
  with strict PEP 8 style and clear project structure.
---

# HomeAssistant Pyscript Skill

## Scope

Use this skill when the user:
- Wants to add or modify pyscript automations or helper functions in Home Assistant.
- Needs to debug or refactor existing pyscript code in the Vastiben/pyscript_HA or Vastiben/pyscript_HA_secours repositories.
- Asks to work on Telegram commands or watchdog logic between the main and backup Home Assistant instances.

Do NOT use this skill for generic Python coding unrelated to Home Assistant or pyscript.

## Environment

- Main Home Assistant:
  - GitHub repository: Vastiben/pyscript_HA
  - This is the primary environment for business logic and automations.
- Backup Home Assistant:
  - GitHub repository: Vastiben/pyscript_HA_secours
  - This instance is dedicated to mutual watchdog and connectivity monitoring with the main HA.

## Project structure conventions

- The GitHub root is mapped to /config/pyscript/ on Home Assistant.
- Use the existing folders and files:
  - `apps.yaml` and `apps/` for pyscript apps and automations.
  - `logs/` for log or debug files pulled from HA to help with troubleshooting.
  - `telegram_commands.py` as the central module for Telegram-based interaction with the phone.
  - Other `.py` files implement specific features (sleep, health, watchdog, wireguard, etc.).

Conventions:
- Place new automations or apps in the `apps/` directory and reference them from `apps.yaml` when appropriate.
- Use `logs/` only for debug/log files; read them to understand issues but do not modify them unless explicitly requested by the user.
- Keep Telegram-related commands and interaction logic centralized in `telegram_commands.py`. If needed, create helper modules and import them from this file.

## PEP 8 style requirements

For all Python code:
- Follow PEP 8 for indentation, line length, naming and imports.
- Indentation: 4 spaces per level, no tabs.
- Line length: target 79 characters for code and about 72 for comments/docstrings.
- Naming:
  - Functions and variables: `snake_case`.
  - Classes: `CapWords`.
  - Modules: lowercase, underscores if needed.
- Imports:
  - Put imports at the top of the file.
  - Group them: standard library, third-party, local modules.
  - Avoid wildcard imports (`from x import *`).
- Spacing and readability:
  - Use spaces around operators and after commas.
  - Prefer one statement per line.
  - Add docstrings or short comments to explain important functions and sections.

When refactoring:
- Preserve the existing business logic.
- Improve readability and structure without changing behavior unless the user explicitly requests a functional change.
- Keep functions relatively small and cohesive instead of large monolithic blocks.

## Main vs backup Home Assistant

- In the **main** repository (Vastiben/pyscript_HA):
  - Implement full home automation, health, sleep analysis, logs management, and Telegram interaction.
  - Organize code into separate modules with clear responsibilities.

- In the **backup** repository (Vastiben/pyscript_HA_secours):
  - Limit logic to watchdog and connectivity monitoring between the two HA instances.
  - Do not introduce complex business logic; keep this repo focused on monitoring and alerting.

## Telegram interactions

- Treat `telegram_commands.py` as the central entry point for Telegram commands:
  - Define or modify commands here.
  - Structure command handlers as clear functions with descriptive names.
  - Use helpers in separate modules if logic becomes complex, and import them into `telegram_commands.py`.

- Ensure all new commands follow PEP 8, have clear parameter names and concise docstrings.

## Workflow with GitHub and pyscript

When the user asks to implement or adjust a feature:

1. Identify whether the change belongs to the main or backup HA repository.
2. Read the relevant existing file(s) in GitHub before editing (e.g. `telegram_commands.py`, `watchdog.py`, `sleep_score.py`).
3. Respect existing structure:
   - Keep imports organized.
   - Maintain module boundaries and responsibilities.
4. Apply changes according to PEP 8 and the project structure conventions.
5. If logs are available in `logs/`, use them to understand errors or behavior before changing code.

Always explain the changes in natural language and, when useful, suggest how to deploy or reload pyscript in Home Assistant after committing the changes.
