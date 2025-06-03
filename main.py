from fastapi import FastAPI
from sqlmodel import create_engine, SQLModel
from models import users, habits, trackers
# from .routers import habits, trackers, users

sqlite_file_name = 'database.db'
sqlite_url = f'sqlite:///{sqlite_file_name}'

engine = create_engine(sqlite_url, echo=True)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

if __name__ == '__main__':
    create_db_and_tables()



app = FastAPI()

