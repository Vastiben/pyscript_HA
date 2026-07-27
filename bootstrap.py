"""
Point d'entrée unique Pyscript.
Importe tous les modules contenant des triggers.
"""


from github_sync.pull import *
from github_sync.github_logs import *

from infrastructure.system_commands import *
from infrastructure.telegram_commands import *
from infrastructure.watchdog import *
from infrastructure.watchdog_summary import *
from infrastructure.wireguard_watchdog import *

from EMS.forecast_tomorrow_24h import *


