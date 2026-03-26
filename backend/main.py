from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.ask import router as ask_router
from backend.api.health import router as health_router
from backend.api.repo import router as repo_router

app = FastAPI(title="DevBrain Backend", version="0.1.0")
app.include_router(health_router)
app.include_router(repo_router)
app.include_router(ask_router)
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/ui/")
