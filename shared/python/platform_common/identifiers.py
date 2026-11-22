"""Safe handling of Unity Catalog identifiers that end up inside SQL text.

Catalog/schema names come from bundle variables and job parameters. They are validated
against a strict pattern before being interpolated, so a bad value fails loudly instead
of producing injectable SQL.
"""

from __future__ import annotations

import re

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,254}")


def validate_identifier(name: str) -> str:
    """Return ``name`` unchanged if it is a plain identifier, else raise ``ValueError``."""
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(
            f"Invalid identifier {name!r}: use letters, digits and underscores only "
            "(must not start with a digit)"
        )
    return name


def qualified_name(*parts: str) -> str:
    """Build a back-quoted, dot-separated name such as ```dev`.`gold`.`sales```."""
    if not parts:
        raise ValueError("qualified_name() needs at least one part")
    return ".".join(f"`{validate_identifier(part)}`" for part in parts)
