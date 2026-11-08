from ninja import Router

router = Router(tags=["Core"])


@router.get("/ping")
def ping(request):
    """Sample ping endpoint from modular router."""
    return {"message": "pong from apps/core"}
