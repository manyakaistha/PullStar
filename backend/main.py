from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.router import router as jobs_router, stars_router
from backend.api.images_router import router as images_router
from backend.api.compute_router import router as compute_router
from backend.api.mcp_router import router as mcp_router

app = FastAPI(title="PullStar API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(images_router)
app.include_router(stars_router)
app.include_router(compute_router)
app.include_router(mcp_router)

@app.get("/")
def read_root():
    return {"status": "PullStar API is running"}
