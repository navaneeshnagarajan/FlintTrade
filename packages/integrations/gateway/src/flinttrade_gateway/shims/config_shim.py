"""Minimal config shim for OpenAlgo broker modules.

Provides values that broker code reads via ``from utils.config import ...``
or similar at import time.
"""

import os as _os

# Broker modules may access these at import time
BROKER_API_KEY = ""
BROKER_API_SECRET = ""
API_KEY_PEPPER = _os.environ.get("API_KEY_PEPPER", "")
DATABASE_URL = ""
