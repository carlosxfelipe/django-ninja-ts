import ninja_ts
from core.api import router as core_router
from ninja.errors import ValidationError as NinjaValidationError
from ninja_extra import NinjaExtraAPI
from ninja_ts.compat import ensure_ninja_extra_compat
from scalar_ninja import Layout, ScalarConfig, ScalarViewer, Theme
from todos.api import router as todos_router

# Optional imports (uncomment when enabling auth):
# from ninja_jwt.controller import NinjaJWTDefaultController

# Compatibility patch: django-ninja 1.8.0 expects .template on all bound routers for webhooks
ensure_ninja_extra_compat()


class _FastifyScalarViewer(ScalarViewer):
    """Apply Scalar's built-in 'fastify' theme (not yet in scalar_ninja's Theme enum)."""

    def render_page(self, request, api):
        response = super().render_page(request, api)
        response.content = response.content.replace(
            b'"theme": "none"',
            b'"theme": "fastify"',
        )
        return response


api = NinjaExtraAPI(
    title="Ninja API",
    version="1.0.0",
    description="Simple API for managing todo items.",
    docs=_FastifyScalarViewer(ScalarConfig(layout=Layout.CLASSIC, theme=Theme.NONE)),
)

_MISSING_FIELD_MESSAGES = {
    "id": "Todo ID is required",
    "title": "Title is required",
    "priority": "Priority is required",
}


@api.exception_handler(NinjaValidationError)
def validation_error_handler(request, exc: NinjaValidationError):
    errors = []
    for err in exc.errors:
        item = dict(err)
        if item.get("type") == "missing":
            loc = item.get("loc") or ()
            field = str(loc[-1]) if loc else ""
            if field in _MISSING_FIELD_MESSAGES:
                item["msg"] = _MISSING_FIELD_MESSAGES[field]
        errors.append(item)
    return api.create_response(request, {"detail": errors}, status=422)


# Optional JWT endpoints (uncomment if using auth):
# api.register_controllers(NinjaJWTDefaultController)

# Register modular routers
api.add_router("", core_router)
api.add_router("/todos", todos_router)

# Serve /api/sdk.ts and /api/types.d.ts (hidden from OpenAPI; only when DEBUG=True).
# In production, export at build time: `python manage.py generate_ts_sdk -o <file>`.
ninja_ts.install(api)
