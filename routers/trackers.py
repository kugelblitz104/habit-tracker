from fastapi import APIRouter, Depends
from ..core.dependencies import get_db
from ..models import *
from typing import Annotated
from sqlalchemy.orm import Session

router = APIRouter(
    prefix='/trackers',
    tags=['trackers'],
    responses={404: {"description": "Not found"}}
)

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
        return None
    return TrackerRead.model_validate(tracker)

@router.put('/')
def update_tracker(tracker_update: TrackerUpdate, db: Annotated[Session, Depends(get_db)]):
    db_tracker = db.get(Tracker, tracker_update.id)
    if not db_tracker:
        return None
    tracker_data = TrackerUpdate.model_validate(tracker_update)
    for key, value in tracker_data.model_dump().items():
        if value is not None:
            setattr(db_tracker, key, value)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)

@router.put('/list')
def update_trackers(trackers: list[TrackerUpdate], db: Annotated[Session, Depends(get_db)]):
    updated_trackers = []
    for tracker_update in trackers:
        db_tracker = db.get(Tracker, tracker_update.id)
        if not db_tracker:
            continue
        tracker_data = TrackerUpdate.model_validate(tracker_update)
        for key, value in tracker_data.model_dump().items():
            if value is not None:
                setattr(db_tracker, key, value)
        db.commit()
        db.refresh(db_tracker)
        updated_trackers.append(TrackerRead.model_validate(db_tracker))
    return updated_trackers

@router.delete('/{tracker_id}')
def delete_tracker(tracker_id: int, db: Annotated[Session, Depends(get_db)]):
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        return None
    db.delete(db_tracker)
    db.commit()
    return TrackerDelete(id=tracker_id)

@router.get('/')
def list_trackers(habit_id: int, db: Annotated[Session, Depends(get_db)]):
    db_trackers = db.query(Tracker).filter(getattr(Tracker, "habit_id") == habit_id).all()
    return [TrackerRead.model_validate(t) for t in db_trackers]