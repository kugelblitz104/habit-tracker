from ..models import habits, trackers
from sqlalchemy.orm import Session

def create_tracker(db: Session, tracker: trackers.TrackerCreate):
    db_tracker = trackers.Tracker.model_validate(tracker)
    db.add(db_tracker)
    db.commit()
    db.refresh(db_tracker)
    return db_tracker

def get_tracker(db: Session, tracker_id: int):
    tracker = db.get(trackers.Tracker, tracker_id)
    if not tracker:
        return None
    return trackers.TrackerRead.model_validate(tracker)

def update_tracker(db: Session, tracker_id: int, tracker_update: trackers.TrackerUpdate):
    db_tracker = db.get(trackers.Tracker, tracker_id)
    if not db_tracker:
        return None
    tracker_data = trackers.TrackerUpdate.model_validate(tracker_update)
    for key, value in tracker_data.model_dump().items():
        if value is not None:
            setattr(db_tracker, key, value)
    db.commit()
    db.refresh(db_tracker)
    return trackers.TrackerRead.model_validate(db_tracker)

def delete_tracker(db: Session, tracker_id: int):
    db_tracker = db.get(trackers.Tracker, tracker_id)
    if not db_tracker:
        return None
    db.delete(db_tracker)
    db.commit()
    return trackers.TrackerDelete(id=tracker_id)

def list_trackers(db: Session, habit_id: int):
    db_habit = db.get(habits.Habit, habit_id)
    if not db_habit:
        return trackers.TrackerList(trackers=[])
    db_trackers = db.query(trackers.Tracker).filter(getattr(trackers.Tracker, "habit_id") == habit_id).all()
    return trackers.TrackerList(trackers=[trackers.TrackerRead.model_validate(t) for t in db_trackers])