from sqlmodel import Field, Relationship, SQLModel
from .users import User

class Habit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: User = Relationship(back_populates='habits')
    name: str = Field()
    question: str
    # color:
    # frequency: 
    # reminder:
    # created_date:
    # updated_date:
    # notes: