from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from habit_tracker.core.dependencies import get_db
from habit_tracker.models import (
    Tracker,
    TrackerCreate,
    TrackerRead,
    TrackerUpdate,
)

router = APIRouter(
    prefix="/trackers", tags=["trackers"], responses={404: {"description": "Not found"}}
)

# TODO: Implement authentication and authorization


@router.post("/")
def create_tracker(
    tracker: TrackerCreate, db: Annotated[Session, Depends(get_db)]
) -> TrackerRead:
    db_tracker = Tracker(**tracker.model_dump())
    db.add(db_tracker)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.get("/{tracker_id}")
def read_tracker(
    tracker_id: int, db: Annotated[Session, Depends(get_db)]
) -> TrackerRead:
    tracker = db.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return TrackerRead.model_validate(tracker)


@router.put("/{tracker_id}")
def update_tracker(
    tracker_id: int,
    tracker_update: TrackerUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> TrackerRead:
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker_data = tracker_update.model_dump(exclude_unset=True)
    for key, value in tracker_data.items():
        setattr(db_tracker, key, value)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.delete("/{tracker_id}")
def delete_tracker(
    tracker_id: int, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    db.delete(db_tracker)
    db.commit()
    return JSONResponse(
        content={"detail": "Tracker deleted successfully"}, status_code=200
    )
