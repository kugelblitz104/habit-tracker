from fastapi import APIRouter, Depends
from ..core.dependencies import get_db
from ..crud import users as crud_users
from typing import Annotated
from sqlalchemy.orm import Session

router = APIRouter(
    prefix='/users',
    tags=['users'],
    responses={404: {"description": "Not found"}}
)

@router.get('/')
def read_users(db: Annotated[Session, Depends(get_db)]):
    return crud_users.list_users(db)