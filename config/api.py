from typing import Any, ClassVar

import ninja_ts
from core.api import router as core_router
from ninja_extra import NinjaExtraAPI
from ninja_extra.controllers.base import ControllerBoundRouter
from ninja_jwt.controller import NinjaJWTDefaultController
from scalar_ninja import ScalarConfig, ScalarViewer
from todos.api import router as todos_router

# Compatibility patch: django-ninja 1.8.0 expects .template on all bound routers for webhooks
if not hasattr(ControllerBoundRouter, "template"):

    class _EmptyTemplate:
        webhooks: ClassVar[dict[str, Any]] = {}

    ControllerBoundRouter.template = property(lambda self: _EmptyTemplate())

api = NinjaExtraAPI(
    title="Ninja API",
    version="1.0.0",
    description="API documentation powered by Scalar and Django Ninja",
    docs=ScalarViewer(ScalarConfig(layout="classic")),
)

# JWT endpoints: /api/token/pair, /api/token/refresh, /api/token/verify
api.register_controllers(NinjaJWTDefaultController)


@api.get("/health", tags=["System"])
def health_check(request):
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "django-ninja",
    }


# Register modular routers
api.add_router("/core", core_router)
api.add_router("/todos", todos_router)

# Serve /api/sdk.ts and /api/types.d.ts (hidden from OpenAPI; only when DEBUG=True).
# In production, export at build time: `python manage.py generate_ts_sdk -o <file>`.
ninja_ts.install(api)
