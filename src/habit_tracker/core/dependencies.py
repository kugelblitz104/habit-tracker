from ..database import SessionLocal
from sqlalchemy.orm import Session
from typing import Annotated
from fastapi import Header, HTTPException

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()