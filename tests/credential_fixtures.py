"""Explicit synthetic managed seeds and authentic pre-authority vault fixtures.

Only callers' newly created disposable directories may be hardened here.
These helpers neither admit production mutation roots nor select provenance.
"""

import base64
import json
import os
import sqlite3
from contextlib import closing

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden, harden_directory


def seed_credentials(store, account_id, broker, label, credentials, is_primary=False, adapter_id=None):
    """Seed managed fixture data through the real CAS owner."""
    selector = BrokerSelector(broker if adapter_id is None else adapter_id, account_id)
    version = store.put_credentials(
        selector, broker, label, credentials, expected=store.selector_state(selector).version
    )
    if is_primary:
        mutation = store.apply_primary_projection(store.snapshot_primary_projection(selector, True))
        version = next(item for item in mutation.after_versions if item.selector == selector)
    return version


def legacy_vault(path, password, *, account_id="AB1234", broker="zerodha", adapter_id=None, credentials=None):
    """Build the historical schema directly, never erase new authority markers."""
    harden_directory(path.parent)
    salt = os.urandom(16)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000).derive(password.encode())
    encrypted = Fernet(base64.urlsafe_b64encode(key)).encrypt(
        json.dumps(credentials or {"synthetic": "token"}).encode()
    )
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("""CREATE TABLE accounts (account_id TEXT PRIMARY KEY, broker TEXT NOT NULL,
                        label TEXT NOT NULL, salt BLOB NOT NULL, encrypted_creds BLOB NOT NULL,
                        is_primary INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
        conn.execute(
            "INSERT INTO accounts VALUES(?,?,?,?,?,?,?)",
            (account_id, broker, "Synthetic", salt, encrypted, 0, "2026-01-01T00:00:00+00:00"),
        )
        if adapter_id is not None:
            conn.execute("ALTER TABLE accounts ADD COLUMN adapter_id TEXT NOT NULL DEFAULT ''")
            conn.execute("UPDATE accounts SET adapter_id=?", (adapter_id,))
        conn.commit()
    harden(path)
    return salt, encrypted
