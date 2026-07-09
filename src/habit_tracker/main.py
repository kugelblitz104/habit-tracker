import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from habit_tracker.routers import (
    auth,
    habits,
    imports,
    profiles,
    projects,
    tasks,
    trackers,
    users,
)

load_dotenv()

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

origins = CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(profiles.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(habits.router)
app.include_router(trackers.router)
app.include_router(auth.router)
app.include_router(imports.router)
