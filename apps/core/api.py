import platform
import time

from django.http import HttpResponse
from ninja import Field, Router, Schema

router = Router(tags=["System"])

_STARTED_AT = time.monotonic()


class HealthStatus(Schema):
    status: str = Field(..., description="Service health state", examples=["ok"])
    uptimeSeconds: int = Field(
        ..., description="Process uptime in seconds", examples=[42]
    )
    pythonVersion: str = Field(
        ...,
        description="Python runtime version",
        examples=["3.14.0"],
    )


@router.get(
    "/health",
    response=HealthStatus,
    summary="Service health check",
    description="Returns service liveness and runtime uptime.",
    openapi_extra={
        "responses": {
            200: {
                "description": "Service health status",
            }
        }
    },
)
def health_check(request):
    return {
        "status": "ok",
        "uptimeSeconds": int(time.monotonic() - _STARTED_AT),
        "pythonVersion": platform.python_version(),
    }


@router.get(
    "/ping",
    summary="Ping endpoint",
    description="Standard Django HttpResponse handler exposed in OpenAPI and Scalar.",
    openapi_extra={
        "responses": {
            200: {
                "description": "Plain-text pong response",
                "content": {
                    "text/plain": {
                        "schema": {"type": "string"},
                    }
                },
            }
        }
    },
)
def ping(request):
    return HttpResponse("pong", content_type="text/plain; charset=utf-8")
