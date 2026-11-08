"""django-ninja-ts: end-to-end type-safe TypeScript SDKs for Django Ninja APIs."""

from ninja_ts.generator import TypeScriptGenerator
from ninja_ts.integration import (
    export_sdk,
    export_types,
    generate_sdk,
    generate_types,
    get_openapi_schema,
    install,
)

__version__ = "0.1.0"

__all__ = [
    "TypeScriptGenerator",
    "export_sdk",
    "export_types",
    "generate_sdk",
    "generate_types",
    "get_openapi_schema",
    "install",
]
