"""Non-invoking setup validation shared by the vault and upgrade planner."""

import ipaddress
import json
import re
from urllib.parse import urlsplit

from .broker_identity import BrokerSelector


class BrokerSetupValidationError(ValueError):
    """Invalid non-secret setup; never include untrusted input in errors."""

    def __init__(self) -> None:
        super().__init__("broker_setup_invalid")


def normalise_broker_setup(selector: BrokerSelector, setup: dict[str, object]) -> str:
    """Return canonical bounded OpenAlgo setup without DNS or client I/O."""
    try:
        if (
            type(selector) is not BrokerSelector
            or selector.adapter_id != "openalgo"
            or type(setup) is not dict
            or set(setup) not in ({"base_url"}, {"base_url", "ws_port"})
        ):
            raise ValueError
        selector.__post_init__()
        value = setup["base_url"]
        if (
            type(value) is not str
            or len(value) > 2048
            or not value.isascii()
            or any(ord(c) <= 32 or ord(c) == 127 or c in "\\?#" for c in value)
        ):
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or "@" in parsed.netloc
            or "%" in parsed.netloc
        ):
            raise ValueError
        authority = parsed.netloc
        if authority.startswith("["):
            end = authority.index("]")
            host = "[" + str(ipaddress.IPv6Address(authority[1:end])) + "]"
            tail = authority[end + 1 :]
        else:
            host, separator, port = authority.partition(":")
            tail = separator + port
            if (
                not host
                or len(host) > 253
                or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                    for part in host.removesuffix(".").split(".")
                )
            ):
                raise ValueError
            host = host.lower()
        if tail and (not re.fullmatch(r":[0-9]+", tail) or not 1 <= int(tail[1:]) <= 65535):
            raise ValueError
        result: dict[str, object] = {"base_url": parsed.scheme.lower() + "://" + host + tail}
        if "ws_port" in setup:
            if type(setup["ws_port"]) is not int or not 1 <= setup["ws_port"] <= 65535:
                raise ValueError
            result["ws_port"] = setup["ws_port"]
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 4096:
            raise ValueError
        return encoded
    except (ValueError, TypeError, OverflowError):
        raise BrokerSetupValidationError from None
