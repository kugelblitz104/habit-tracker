import os
from .database import engine, create_db_and_tables 
from fastapi import FastAPI
from sqlmodel import create_engine, SQLModel
from contextlib import asynccontextmanager
from .routers import habits, trackers, users

if __name__ == '__main__':
    create_db_and_tables(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables(engine)
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(users.router)

