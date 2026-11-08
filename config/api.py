from core.api import router as core_router
from ninja_extra import NinjaExtraAPI
from ninja_jwt.controller import NinjaJWTDefaultController
from scalar_ninja import ScalarConfig, ScalarViewer

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
