"""django-ninja-ts: end-to-end type-safe TypeScript SDKs for Django Ninja APIs."""

from ninja_ts.generator import TypeScriptGenerator
from ninja_ts.integration import (
    create_sdk_view,
    create_types_view,
    export_sdk,
    export_types,
    generate_sdk,
    generate_types,
    get_openapi_schema,
    install,
)
from ninja_ts.security import audit_schemas, is_sensitive_field_name

__version__ = "0.1.0"

__all__ = [
    "TypeScriptGenerator",
    "audit_schemas",
    "create_sdk_view",
    "create_types_view",
    "export_sdk",
    "export_types",
    "generate_sdk",
    "generate_types",
    "get_openapi_schema",
    "install",
    "is_sensitive_field_name",
]
