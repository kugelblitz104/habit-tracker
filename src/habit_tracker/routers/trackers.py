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


@router.post("/", status_code=201, summary="Create a new tracker entry")
def create_tracker(
    tracker: TrackerCreate, db: Annotated[Session, Depends(get_db)]
) -> TrackerRead:
    """
    Create a new tracker entry to record habit completion or skip for a specific date.

    - **habit_id**: The ID of the habit being tracked
    - **dated**: The date for this tracker entry
    - **completed**: Whether the habit was completed on this date
    - **skipped**: Whether the habit was skipped on this date
    - **note**: Optional note about this entry
    """
    db_tracker = Tracker(**tracker.model_dump())
    db.add(db_tracker)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.get("/{tracker_id}", summary="Get a tracker entry by ID")
def read_tracker(
    tracker_id: int, db: Annotated[Session, Depends(get_db)]
) -> TrackerRead:
    """
    Retrieve a specific tracker entry by its ID.

    - **tracker_id**: The unique identifier of the tracker entry to retrieve
    """
    tracker = db.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return TrackerRead.model_validate(tracker)


@router.put("/{tracker_id}", summary="Replace a tracker entry (full update)")
def update_tracker(
    tracker_id: int,
    tracker_update: TrackerUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> TrackerRead:
    """
    Replace all fields of an existing tracker entry. All fields must be provided.

    This performs a full replacement of the tracker resource.
    Use PATCH if you want to update only specific fields.

    - **tracker_id**: The unique identifier of the tracker entry to update
    """
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker_data = tracker_update.model_dump()
    for key, value in tracker_data.items():
        setattr(db_tracker, key, value)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.patch("/{tracker_id}", summary="Update a tracker entry (partial update)")
def patch_tracker(
    tracker_id: int,
    tracker_update: TrackerUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> TrackerRead:
    """
    Update specific fields of an existing tracker entry. Only provided fields will be updated.

    This performs a partial update of the tracker resource.
    Use PUT if you want to replace the entire resource.

    - **tracker_id**: The unique identifier of the tracker entry to update

    You can update any combination of these fields:
    - **dated**: The date for this tracker entry
    - **completed**: Whether the habit was completed on this date
    - **skipped**: Whether the habit was skipped on this date
    - **note**: Optional note about this entry
    """
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker_data = tracker_update.model_dump(exclude_unset=True)
    for key, value in tracker_data.items():
        setattr(db_tracker, key, value)
    db.commit()
    db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.delete("/{tracker_id}", summary="Delete a tracker entry")
def delete_tracker(
    tracker_id: int, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    """
    Delete a tracker entry by its ID.

    - **tracker_id**: The unique identifier of the tracker entry to delete

    This action cannot be undone.
    """
    db_tracker = db.get(Tracker, tracker_id)
    if not db_tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    db.delete(db_tracker)
    db.commit()
    return JSONResponse(
        content={"detail": "Tracker deleted successfully"}, status_code=200
    )
