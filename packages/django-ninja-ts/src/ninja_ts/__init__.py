"""django-ninja-ts: end-to-end type-safe TypeScript SDKs for Django Ninja APIs."""

from ninja_ts.generator import TypeScriptGenerator, detect_ts_import_extension
from ninja_ts.integration import (
    SdkDriftError,
    SdkSyncResult,
    check_sdk,
    export_sdk,
    generate_sdk,
    get_openapi_schema,
    sync_sdk,
)
from ninja_ts.security import audit_schemas, is_sensitive_field_name

__version__ = "0.1.0"

__all__ = [
    "SdkDriftError",
    "SdkSyncResult",
    "TypeScriptGenerator",
    "audit_schemas",
    "check_sdk",
    "detect_ts_import_extension",
    "export_sdk",
    "generate_sdk",
    "get_openapi_schema",
    "is_sensitive_field_name",
    "sync_sdk",
]
