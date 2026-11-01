from fastapi import APIRouter
from core.compute import system_capabilities

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/compute")
def get_compute_capabilities():
    return system_capabilities()
