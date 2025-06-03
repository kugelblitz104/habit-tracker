import os
from fastapi import FastAPI
from sqlmodel import create_engine, SQLModel
from models import users, habits, trackers
from contextlib import asynccontextmanager
# from .routers import habits, trackers, users

sqlite_file_name = 'database.db'
sqlite_url = f'sqlite:///{sqlite_file_name}'

def create_db_and_tables(engine):
    SQLModel.metadata.create_all(engine)

if __name__ == '__main__':
    create_db_and_tables()

@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_engine(sqlite_url, echo=True)
    create_db_and_tables(engine)
    yield
    os.remove(f'./{sqlite_file_name}')

app = FastAPI(lifespan=lifespan)

