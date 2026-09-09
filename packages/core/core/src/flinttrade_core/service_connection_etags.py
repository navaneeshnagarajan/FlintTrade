"""Bounded RFC 9110 syntax for one strong service-collection entity tag."""

from __future__ import annotations

MAX_IF_MATCH_FIELD_OCTETS = 4096


def parse_single_strong_entity_tag(value: object) -> str:
    """Return one exact strong entity tag after removing only external OWS."""
    if type(value) is not str:
        raise ValueError("invalid entity tag")
    try:
        encoded = value.encode("latin-1")
    except UnicodeEncodeError:
        raise ValueError("invalid entity tag") from None
    if len(encoded) > MAX_IF_MATCH_FIELD_OCTETS:
        raise ValueError("entity tag is too large")
    tag = value.strip(" \t")
    if len(tag) < 2 or tag[0] != '"' or tag[-1] != '"':
        raise ValueError("invalid entity tag")
    for character in tag[1:-1]:
        codepoint = ord(character)
        if codepoint != 0x21 and not 0x23 <= codepoint <= 0x7E and not 0x80 <= codepoint <= 0xFF:
            raise ValueError("invalid entity tag")
    return tag
