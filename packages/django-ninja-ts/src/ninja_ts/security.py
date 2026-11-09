"""Security auditing for Django Ninja schemas and OpenAPI response contracts.

Scans response schemas for sensitive fields (e.g. password hashes, secret keys,
cryptographic salts, tokens, card pins) that may be unintentionally leaked
in API responses.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ninja import NinjaAPI

    ApiOrSchema = NinjaAPI | dict[str, Any]

# Regex patterns mapped to human-readable security descriptions
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(pass(word|wd)?_?hash|passhash|pwdhash)", re.IGNORECASE),
        "password hash",
    ),
    (
        re.compile(r"(pass(word|wd)?_?salt|^salt$)", re.IGNORECASE),
        "cryptographic salt",
    ),
    (
        re.compile(r"secret", re.IGNORECASE),
        "secret key",
    ),
    (
        re.compile(
            r"(private|signing|encryption|master)_?key",
            re.IGNORECASE,
        ),
        "private/cryptographic key",
    ),
    (
        re.compile(
            r"(reset|refresh|auth|session|bearer)_?token",
            re.IGNORECASE,
        ),
        "authentication/session token",
    ),
    (
        re.compile(
            r"(card_?)?(cvv|cvc|card_?pin|security_code)",
            re.IGNORECASE,
        ),
        "payment security code",
    ),
    (
        re.compile(r"^password$", re.IGNORECASE),
        "plaintext password",
    ),
]


def is_sensitive_field_name(name: str) -> tuple[bool, str]:
    """Check if an exported field name strongly resembles a sensitive secret."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", name).lower()
    for pattern, reason in _SENSITIVE_PATTERNS:
        if pattern.search(name) or pattern.search(cleaned):
            return True, reason
    return False, ""


def audit_schemas(api_or_schema: ApiOrSchema) -> list[str]:
    """Audit response schemas for sensitive fields inadvertently exposed in the API contract.

    Returns a list of warning descriptions. An empty list indicates no sensitive
    fields were found in response contracts.
    """
    from ninja_ts.integration import get_openapi_schema

    if isinstance(api_or_schema, dict):
        openapi = api_or_schema
    else:
        openapi = get_openapi_schema(api_or_schema, path_prefix="")

    schemas: dict[str, Any] = (openapi.get("components") or {}).get("schemas") or {}
    paths: dict[str, Any] = openapi.get("paths") or {}

    response_schemas: set[str] = set()
    ref_prefix = "#/components/schemas/"

    def collect_refs(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(ref_prefix):
                response_schemas.add(ref[len(ref_prefix) :])
            for v in node.values():
                collect_refs(v)
        elif isinstance(node, list):
            for item in node:
                collect_refs(item)

    for path_item in paths.values():
        if isinstance(path_item, dict):
            for method_op in path_item.values():
                if isinstance(method_op, dict) and "responses" in method_op:
                    collect_refs(method_op["responses"])

    # Expand reachable schemas through allOf, anyOf, oneOf, properties
    visited: set[str] = set()
    queue = list(response_schemas)
    while queue:
        s_name = queue.pop()
        if s_name in visited or s_name not in schemas:
            continue
        visited.add(s_name)
        schema = schemas[s_name]
        collect_refs(schema)
        for s in response_schemas - visited:
            if s not in queue:
                queue.append(s)

    warnings: list[str] = []

    for schema_name in sorted(visited):
        schema = schemas[schema_name]
        if not isinstance(schema, dict):
            continue
        properties: dict[str, Any] = schema.get("properties") or {}
        for prop_name, prop_data in properties.items():
            if not isinstance(prop_data, dict):
                continue
            desc = str(prop_data.get("description") or "").lower()
            if "nowarn" in desc or "no-audit" in desc or "safe" in desc:
                continue

            is_sensitive, reason = is_sensitive_field_name(prop_name)
            if is_sensitive:
                warnings.append(
                    f"Schema '{schema_name}' exposes field '{prop_name}' ({reason}) in API response contract."
                )

    return warnings
