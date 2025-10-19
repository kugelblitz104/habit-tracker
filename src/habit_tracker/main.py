import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from habit_tracker.database import create_db_and_tables, engine
from habit_tracker.routers import habits, trackers, users

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    create_db_and_tables(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables(engine)
    yield


app = FastAPI(
    lifespan=lifespan,
)

origins = ["http://localhost:5173"]

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
