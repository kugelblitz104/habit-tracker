import os
from .database import engine, create_db_and_tables 
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from sqlmodel import create_engine, SQLModel
from contextlib import asynccontextmanager
from .routers import habits, trackers, users

if __name__ == '__main__':
    create_db_and_tables(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables(engine)
    yield

# middleware = [
#     Middleware(
#         CORSMiddleware,
#         allow_origins=['*'],
#         allow_credentials=True,
#         allow_methods=['*'],
#         allow_headers=['*']
#     )
# ]

app = FastAPI(
    lifespan=lifespan,
    # middleware=middleware
)

origins = [
    "*"
]

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


