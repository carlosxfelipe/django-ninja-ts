"""Django Ninja integration: schema extraction, file export and optional HTTP routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ninja_ts.compat import ensure_ninja_extra_compat
from ninja_ts.generator import TypeScriptGenerator

if TYPE_CHECKING:
    from ninja import NinjaAPI

    ApiOrSchema = NinjaAPI | dict[str, Any]

TS_CONTENT_TYPE = "application/typescript; charset=utf-8"

_UNSET: Any = object()


def get_openapi_schema(
    api: NinjaAPI, *, path_prefix: str | None = None
) -> dict[str, Any]:
    """Return the API's OpenAPI document as plain JSON-compatible data.

    ``path_prefix=None`` lets Ninja resolve the mount point from the URLconf (e.g. ``/api/``);
    pass ``""`` to generate paths relative to the API root without touching the URLconf.
    """
    from django.core.serializers.json import DjangoJSONEncoder

    ensure_ninja_extra_compat()
    schema = api.get_openapi_schema(path_prefix=path_prefix)
    # Round-trip through JSON: normalizes int status codes, Decimals, enums, lazy strings...
    return json.loads(json.dumps(schema, cls=DjangoJSONEncoder))


def _uses_response_exclusions(api: NinjaAPI) -> bool:
    """True if any operation may omit response fields (exclude_none/unset/defaults)."""
    for bound_router in api._get_bound_routers():
        for path_view in bound_router.path_operations.values():
            for operation in getattr(path_view, "operations", []):
                if any(
                    getattr(operation, f, False)
                    for f in ("exclude_none", "exclude_unset", "exclude_defaults")
                ):
                    return True
    return False


def _generator(api: ApiOrSchema, path_prefix: str | None) -> TypeScriptGenerator:
    if isinstance(api, dict):
        return TypeScriptGenerator(api)
    openapi = get_openapi_schema(api, path_prefix=path_prefix)
    return TypeScriptGenerator(
        openapi, responses_include_all_fields=not _uses_response_exclusions(api)
    )


def generate_types(api: ApiOrSchema, *, path_prefix: str | None = None) -> str:
    """TypeScript declarations (``.d.ts``) for a NinjaAPI (or a raw OpenAPI dict)."""
    return _generator(api, path_prefix).generate_types()


def generate_sdk(api: ApiOrSchema, *, path_prefix: str | None = None) -> str:
    """Standalone TypeScript SDK (``.ts``) for a NinjaAPI (or a raw OpenAPI dict)."""
    return _generator(api, path_prefix).generate_sdk()


def _write(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def export_types(
    api: ApiOrSchema, path: str | Path, *, path_prefix: str | None = None
) -> Path:
    """Write the ``.d.ts`` declarations to ``path`` (parent directories are created)."""
    return _write(path, generate_types(api, path_prefix=path_prefix))


def export_sdk(
    api: ApiOrSchema, path: str | Path, *, path_prefix: str | None = None
) -> Path:
    """Write the standalone SDK to ``path`` (parent directories are created)."""
    return _write(path, generate_sdk(api, path_prefix=path_prefix))


def install(
    api: NinjaAPI,
    *,
    sdk_url: str | None = "/sdk.ts",
    types_url: str | None = "/types.d.ts",
    enabled: bool | None = None,
    auth: Any = _UNSET,
) -> None:
    """Serve the SDK and declarations from the API itself (hidden from the OpenAPI schema).

    Must be called before ``api.urls`` is evaluated (i.e. in the module defining the API).

    - ``enabled`` defaults to ``settings.DEBUG``: in production prefer exporting the SDK at
      build time (``manage.py generate_ts_sdk``) instead of exposing your API contract.
    - ``auth`` is forwarded to Ninja (e.g. ``django_auth``); by default the API's auth applies.
    - Pass ``None`` as ``sdk_url`` / ``types_url`` to skip one of the routes.
    """
    from django.conf import settings
    from django.http import HttpResponse

    if enabled is None:
        enabled = bool(settings.DEBUG)
    if not enabled:
        return

    route_kwargs: dict[str, Any] = {"include_in_schema": False}
    if auth is not _UNSET:
        route_kwargs["auth"] = auth

    def respond(content: str) -> HttpResponse:
        response = HttpResponse(content, content_type=TS_CONTENT_TYPE)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    if sdk_url:

        @api.get(sdk_url, url_name="ninja_ts_sdk", **route_kwargs)
        def ninja_ts_sdk(request):
            return respond(generate_sdk(api))

    if types_url:

        @api.get(types_url, url_name="ninja_ts_types", **route_kwargs)
        def ninja_ts_types(request):
            return respond(generate_types(api))


def create_sdk_view(
    api: ApiOrSchema, *, path_prefix: str | None = None, enabled: bool | None = None
):
    """Return a standard Django view that dynamically serves the TypeScript SDK.

    Can be mounted directly in Django ``urlpatterns``:
    ``path("api/sdk.ts", create_sdk_view(api))``
    """
    from django.conf import settings
    from django.http import Http404, HttpRequest, HttpResponse

    def sdk_view(request: HttpRequest) -> HttpResponse:
        is_enabled = bool(settings.DEBUG) if enabled is None else bool(enabled)
        if not is_enabled:
            raise Http404("TypeScript SDK endpoint is disabled.")
        response = HttpResponse(
            generate_sdk(api, path_prefix=path_prefix), content_type=TS_CONTENT_TYPE
        )
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    return sdk_view


def create_types_view(
    api: ApiOrSchema, *, path_prefix: str | None = None, enabled: bool | None = None
):
    """Return a standard Django view that dynamically serves TypeScript declarations (.d.ts).

    Can be mounted directly in Django ``urlpatterns``:
    ``path("api/types.d.ts", create_types_view(api))``
    """
    from django.conf import settings
    from django.http import Http404, HttpRequest, HttpResponse

    def types_view(request: HttpRequest) -> HttpResponse:
        is_enabled = bool(settings.DEBUG) if enabled is None else bool(enabled)
        if not is_enabled:
            raise Http404("TypeScript types endpoint is disabled.")
        response = HttpResponse(
            generate_types(api, path_prefix=path_prefix), content_type=TS_CONTENT_TYPE
        )
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    return types_view
