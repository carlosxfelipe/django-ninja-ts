"""Compatibility shims for third-party packages."""

from __future__ import annotations

from typing import Any, ClassVar


def ensure_ninja_extra_compat() -> None:
    """Make ``django-ninja-extra`` controllers work with django-ninja >= 1.8 schema generation.

    django-ninja 1.8 reads ``bound_router.template.webhooks`` while building the OpenAPI
    schema, but ``ninja_extra``'s ``ControllerBoundRouter`` has no ``template`` attribute,
    so ``api.get_openapi_schema()`` raises ``AttributeError``. Controllers never declare
    webhooks, so exposing an empty registry is safe. No-op when not needed.
    """
    try:
        from ninja_extra.controllers.base import ControllerBoundRouter
    except ImportError:
        return
    if hasattr(ControllerBoundRouter, "template"):
        return

    class _NoWebhooks:
        webhooks: ClassVar[dict[str, Any]] = {}

    ControllerBoundRouter.template = property(lambda self: _NoWebhooks())  # type: ignore[attr-defined]
