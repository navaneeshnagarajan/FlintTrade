"""Minimal config shim for OpenAlgo broker modules.

Provides values that broker code reads via ``from utils.config import ...``
or similar at import time.
"""

# Broker modules may access these at import time
BROKER_API_KEY = ""
BROKER_API_SECRET = ""
API_KEY_PEPPER = "flinttrade-gateway-pepper-default"
DATABASE_URL = ""
