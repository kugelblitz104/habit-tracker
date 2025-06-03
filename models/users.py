from sqlmodel import Field, SQLModel
from pydantic import EmailStr
from datetime import datetime

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    first_name: str 
    last_name: str 
    email: EmailStr 
    password_hash: str 
    created_date: datetime
    updated_date: datetime | None