from fastapi import APIRouter, Depends, HTTPException
from ..core.dependencies import get_db
from ..models import *
from typing import Annotated
from sqlalchemy.orm import Session

router = APIRouter(
    prefix='/trackers',
    tags=['trackers'],
    responses={404: {"description": "Not found"}}
)

# TODO: Implement authentication and authorization
# TODO: Disallow creation of trackers on the same date

@router.post('/')
def create_tracker(tracker: TrackerCreate, db: Annotated[Session, Depends(get_db)]):
    db_tracker = Tracker.model_validate(tracker)
    db.add(db_tracker)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)

@router.get('/{tracker_id}')
def read_tracker(tracker_id: int, db: Annotated[Session, Depends(get_db)]):
    tracker = db.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return TrackerRead.model_validate(tracker)

@router.put('/{tracker_id}')
def update_tracker(tracker_id: int, tracker_update: TrackerUpdate, db: Annotated[Session, Depends(get_db)]):
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker_data = TrackerUpdate.model_validate(tracker_update)
    for key, value in tracker_data.model_dump().items():
        if value is not None:
            setattr(db_tracker, key, value)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)

@router.delete('/{tracker_id}')
def delete_tracker(tracker_id: int, db: Annotated[Session, Depends(get_db)]):
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    db.delete(db_tracker)
    db.commit()
    return {"detail": "Tracker deleted successfully"}

# @router.get('/')
# def list_trackers(habit_id: int, db: Annotated[Session, Depends(get_db)]):
#     db_trackers = db.query(Tracker).filter(getattr(Tracker, "habit_id") == habit_id).all()
#     return [TrackerRead.model_validate(t) for t in db_trackers]