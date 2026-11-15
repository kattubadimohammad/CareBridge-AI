from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.database import Base, engine
from app.routers import web_router, api_router
from app.routers.auth import auth_router
from app.routers.profile import profile_router
from app.routers.medications import medications_router
from app.routers.adherence import adherence_router
from app.routers.appointments import appointments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on application startup
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    description="Accessible Elderly Care and Medication Management Platform",
    version="0.2.0",
    lifespan=lifespan,
)

# Mount static assets for CSS, JS, and media
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Mount API routers
app.include_router(web_router)
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(medications_router)
app.include_router(adherence_router)
app.include_router(appointments_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
