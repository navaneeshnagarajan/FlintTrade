"""Pytest configuration for ditto tests.

Ditto account api_keys are stored in the canonical credential vault
(:class:`flinttrade_gateway.credentials.CredentialStore`); tests pass a
``master_password`` (or an injected store) to ``AccountManager`` directly, so no
process-wide encryption key is set here.
"""

from __future__ import annotations
