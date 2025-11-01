from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from habit_tracker.core.dependencies import get_db
from habit_tracker.models import (
    Habit,
    HabitCreate,
    HabitKPIs,
    HabitRead,
    HabitUpdate,
    Streak,
    Tracker,
    TrackerList,
    TrackerRead,
)

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


@router.post("/", status_code=201, summary="Create a new habit")
async def create_habit(
    habit: HabitCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> HabitRead:
    """
    Create a new habit with the following information:

    - **user_id**: The ID of the user who owns this habit
    - **name**: Name of the habit
    - **question**: The daily question to prompt for this habit
    - **color**: Color code for visual representation
    - **frequency**: How many times the habit should be completed within the range
    - **range**: The number of days within which the frequency should be met
    - **reminder**: Whether to enable reminders for this habit
    - **notes**: Optional additional notes about the habit
    """
    db_habit = Habit(**habit.model_dump())
    db.add(db_habit)
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.get("/{habit_id}", summary="Get a habit by ID")
async def read_habit(
    habit_id: int, db: Annotated[AsyncSession, Depends(get_db)]
) -> HabitRead:
    """
    Retrieve a specific habit by its ID.

    - **habit_id**: The unique identifier of the habit to retrieve
    """
    habit = await db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return HabitRead.model_validate(habit)


@router.get("/{habit_id}/trackers", summary="List all trackers for a habit")
async def list_habit_trackers(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of trackers to return (1-100)",
    ),
) -> TrackerList:
    """
    Get all tracker entries for a specific habit, ordered by date (most recent first).

    - **habit_id**: The unique identifier of the habit
    - **limit**: Maximum number of trackers to return (default: 5, max: 100)

    Returns tracker entries showing completion/skip status for each date.
    """
    habit = await db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    result = await db.execute(
        select(Tracker)
        .filter(Tracker.habit_id == habit_id)
        .order_by(Tracker.dated.desc())
        .limit(limit if limit > 0 else None)
    )
    db_trackers = result.scalars().all()

    return TrackerList(
        trackers=[TrackerRead.model_validate(t) for t in db_trackers],
        total=len(db_trackers),
        limit=limit,
        offset=0,
    )


@router.get("/{habit_id}/kpis", summary="Get habit KPIs and statistics")
async def get_habit_kpis(
    habit_id: int, db: Annotated[AsyncSession, Depends(get_db)]
) -> HabitKPIs:
    """
    Get Key Performance Indicators (KPIs) for a specific habit.

    - **habit_id**: The unique identifier of the habit

    Returns comprehensive statistics including:
    - Current streak length
    - Longest streak achieved
    - Total completions
    - 30-day completion rate
    - Overall completion rate since creation
    - Last completed date
    """
    habit = await read_habit(habit_id, db=db)

    thirty_day_completions = (
        await db.execute(
            select(func.count()).filter(
                Tracker.habit_id == habit_id,
                Tracker.dated >= datetime.now() - timedelta(days=30),
            )
        )
    ).scalar()

    result = await db.execute(select(func.count()).filter(Tracker.habit_id == habit_id))
    count_completions = result.scalar()

    days_active = (datetime.now() - habit.created_date).days

    last_tracker = (
        await db.execute(
            select(Tracker)
            .filter(Tracker.habit_id == habit_id)
            .order_by(Tracker.dated.desc())
            .limit(1)
        )
    ).scalar()

    streaks = await get_habit_streaks(habit_id, db=db)
    if len(streaks) > 0:
        current_streak = streaks[-1].length()
        longest_streak = max((s.length() for s in streaks), default=0)

    if not count_completions:
        count_completions = 0

    if not thirty_day_completions:
        thirty_day_completions = 0

    kpis = HabitKPIs(
        id=habit.id,
        current_streak=current_streak if len(streaks) > 0 else 0,
        longest_streak=longest_streak if len(streaks) > 0 else 0,
        total_completions=count_completions,
        thirty_day_completion_rate=(
            thirty_day_completions / 30 if thirty_day_completions > 0 else 0
        ),
        overall_completion_rate=(
            count_completions / days_active if days_active > 0 else 0
        ),
        last_completed_date=last_tracker.dated if last_tracker else None,
    )

    return HabitKPIs.model_validate(kpis)


@router.get("/{habit_id}/streaks", summary="Get habit streaks")
async def get_habit_streaks(
    habit_id, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[Streak]:
    """
    Get all streak periods for a specific habit.

    - **habit_id**: The unique identifier of the habit

    Returns a list of all streak periods with start and end dates.
    Streaks are calculated based on the habit's frequency and range settings.
    """
    habit = await read_habit(habit_id, db)
    days_since_created = (datetime.now().date() - habit.created_date.date()).days

    tracker_list = await list_habit_trackers(
        habit_id, db=db, limit=days_since_created + 1
    )
    all_trackers = tracker_list.trackers
    completed_dates = [x.dated for x in all_trackers if x.completed]
    skipped_dates = [x.dated for x in all_trackers if x.skipped]

    streak_continued = []

    for days_since in range(days_since_created + 1):
        moving_date = habit.created_date.date() + timedelta(days=days_since)
        window_start = moving_date - timedelta(days=habit.range - 1)

        # Count completions in window
        completions = sum(
            1 for d in completed_dates if window_start <= d <= moving_date
        )

        if completions >= habit.frequency:
            streak_continued.append(moving_date)

    streak_continued.extend([x for x in skipped_dates if x not in streak_continued])
    streak_continued.sort()

    streaks = []
    moving_streak = None

    for streak_day in streak_continued:
        if moving_streak:
            # Check if this day is within tolerance of the last streak day
            gap = (streak_day - moving_streak.end_date).days
            if gap <= habit.range:
                moving_streak.end_date = streak_day
            else:
                # Gap too large, start new streak
                streaks.append(moving_streak)
                moving_streak = Streak.from_date(
                    streak_day - timedelta(days=habit.range - 1)
                )
                moving_streak.end_date = streak_day
        else:
            # Start new streak, backdated by the range
            moving_streak = Streak.from_date(
                streak_day - timedelta(days=habit.range - 1)
            )
            moving_streak.end_date = streak_day

    if moving_streak:
        streaks.append(moving_streak)
    return streaks


@router.put("/{habit_id}", summary="Replace a habit (full update)")
async def update_habit(
    habit_id: int,
    habit_update: HabitUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HabitRead:
    """
    Replace all fields of an existing habit. All fields must be provided.

    This performs a full replacement of the habit resource.
    Use PATCH if you want to update only specific fields.

    - **habit_id**: The unique identifier of the habit to update
    """
    db_habit = await db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    habit_data = habit_update.model_dump()
    for key, value in habit_data.items():
        setattr(db_habit, key, value)
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.patch("/{habit_id}", summary="Update a habit (partial update)")
async def patch_habit(
    habit_id: int,
    habit_update: HabitUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HabitRead:
    """
    Update specific fields of an existing habit. Only provided fields will be updated.

    This performs a partial update of the habit resource.
    Use PUT if you want to replace the entire resource.

    - **habit_id**: The unique identifier of the habit to update

    You can update any combination of these fields:
    - **name**: Name of the habit
    - **question**: The daily question to prompt for this habit
    - **color**: Color code for visual representation
    - **frequency**: How many times the habit should be completed within the range
    - **range**: The number of days within which the frequency should be met
    - **reminder**: Whether to enable reminders for this habit
    - **notes**: Optional additional notes about the habit
    """
    db_habit = await db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    habit_data = habit_update.model_dump(exclude_unset=True)
    for key, value in habit_data.items():
        setattr(db_habit, key, value)
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.delete("/{habit_id}", summary="Delete a habit")
async def delete_habit(
    habit_id: int, db: Annotated[AsyncSession, Depends(get_db)]
) -> JSONResponse:
    """
    Delete a habit by its ID.

    - **habit_id**: The unique identifier of the habit to delete

    This action cannot be undone. All associated tracker entries will also be deleted.
    """
    db_habit = await db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    await db.delete(db_habit)
    await db.commit()
    return JSONResponse(content={"detail": "Habit deleted successfully"})
