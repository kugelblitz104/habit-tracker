import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from habit_tracker.routers import habits, trackers, users

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
app.include_router(habits.router)
app.include_router(trackers.router)
