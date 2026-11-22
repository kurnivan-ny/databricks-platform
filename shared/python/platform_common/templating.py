"""``${name}`` placeholder rendering for SQL and YAML templates.

Only placeholders are substituted and every value must be a plain identifier
(catalog/schema names), so templates cannot be used to inject arbitrary SQL.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from platform_common.identifiers import validate_identifier

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def placeholders(template: str) -> set[str]:
    return set(PLACEHOLDER.findall(template))


def render(template: str, values: Mapping[str, str]) -> str:
    """Replace ``${key}`` placeholders; unknown keys and non-identifier values raise."""

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"no value supplied for placeholder ${{{key}}}")
        return validate_identifier(values[key])

    return PLACEHOLDER.sub(substitute, template)
