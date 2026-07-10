from datetime import date, datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_profile,
    resolve_timezone,
)
from habit_tracker.models import (
    CalendarConnection,
    CalendarConnectionCreate,
    CalendarConnectionList,
    CalendarConnectionRead,
    CalendarConnectionUpdate,
    CalendarEventList,
    CalendarEventRead,
)
from habit_tracker.schemas.db_models import User
from habit_tracker.services.calendar_events import (
    IcsFetcher,
    get_ics_fetcher,
    parse_events,
    refresh_connection,
)

router = APIRouter(
    prefix="/calendar-connections",
    tags=["calendar-connections"],
    responses={404: {"description": "Not found"}},
)


async def _get_connection_and_authorize(
    db: AsyncSession, connection_id: int, current_user: User
) -> CalendarConnection:
    """Fetch a calendar connection by ID (404 if missing) and authorize the
    caller against the owning profile."""
    connection = await db.get(CalendarConnection, connection_id)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar connection not found",
        )
    await authorize_parent_profile(
        db, connection.profile_id, current_user, "calendar connection"
    )
    return connection


@router.get("/", summary="List calendar connections for a profile")
async def list_calendar_connections(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose connections to list"),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of connections to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of connections to skip"),
) -> CalendarConnectionList:
    """
    Get a paginated list of read-only ICS calendar subscriptions belonging to
    a profile, ordered by creation date.

    - **profile_id**: The profile whose connections to list (required)
    - **limit**: Maximum number of connections to return (default: 100, max: 100)
    - **offset**: Number of connections to skip (default: 0)
    """
    await get_owned_profile(db, profile_id, current_user, "calendar connection")

    result = await db.execute(
        select(CalendarConnection)
        .filter(CalendarConnection.profile_id == profile_id)
        .order_by(CalendarConnection.created_date)
        .limit(limit)
        .offset(offset)
    )
    db_connections = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(CalendarConnection.profile_id == profile_id)
    )
    total = count_result.scalar() or 0

    return CalendarConnectionList(
        calendar_connections=[
            CalendarConnectionRead.model_validate(c) for c in db_connections
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new calendar connection",
)
async def create_calendar_connection(
    connection: CalendarConnectionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CalendarConnectionRead:
    """
    Subscribe a profile to a read-only ICS calendar feed:

    - **profile_id**: The ID of the profile this connection belongs to
    - **name**: Display name for the calendar
    - **color**: Hex color code for the calendar's events
    - **url**: The ICS feed URL (http:// or https://)
    - **provider**: Optional free-form label ("Google", "iCloud", ...)
    - **enabled**: Whether the calendar's events are included (default: true)
    """
    await get_owned_profile(db, connection.profile_id, current_user, "calendar connection")

    db_connection = CalendarConnection(**connection.model_dump())
    db.add(db_connection)
    await db.commit()
    await db.refresh(db_connection)
    return CalendarConnectionRead.model_validate(db_connection)


# NOTE: static route declared BEFORE the dynamic /{connection_id} routes so
# FastAPI does not try to parse "events" as a connection id
@router.get("/events", summary="Get calendar events for a profile over a day range")
async def list_calendar_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    fetcher: Annotated[IcsFetcher, Depends(get_ics_fetcher)],
    profile_id: int = Query(description="The profile whose calendar events to list"),
    target_date: Optional[date] = Query(
        default=None, description="The day to list events for (default: today)"
    ),
    days: int = Query(
        default=1,
        ge=1,
        le=14,
        description=(
            "Number of days to return events for, starting at target_date "
            "(default: 1, max: 14)"
        ),
    ),
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, the "
            "day runs from midnight to midnight in this zone and the default "
            "target_date is today in this zone; when omitted, day boundaries "
            "are interpreted in each feed's own timezone (legacy behavior)."
        ),
    ),
) -> CalendarEventList:
    """
    Fetch, cache and parse the profile's enabled ICS calendar feeds and return
    the normalized events of the window [target_date, target_date + days)
    (recurrences expanded). Each event carries the **event_date** it belongs
    to; events are ordered by event_date, then all-day events first, then
    timed events by start time.

    Successful fetches are cached for 15 minutes; a failing feed keeps serving
    its stale cache, is not re-attempted for 5 minutes, and its failure is
    reported in **errors** ("Name: HTTP 404") instead of failing the whole
    response.

    - **profile_id**: The profile whose calendar events to list (required)
    - **target_date**: The first day to list events for, YYYY-MM-DD (default: today)
    - **days**: Number of days in the window starting at target_date (default: 1, max: 14)
    - **tz**: Optional IANA timezone for day boundaries (invalid name -> 422)
    """
    await get_owned_profile(db, profile_id, current_user, "calendar connection")

    zone = resolve_timezone(tz)

    if target_date is None:
        # "Today" is timezone-dependent: use the caller's zone when given,
        # otherwise fall back to server-local today
        target_date = datetime.now(zone).date() if zone else date.today()

    result = await db.execute(
        select(CalendarConnection)
        .filter(
            CalendarConnection.profile_id == profile_id,
            CalendarConnection.enabled.is_(True),
        )
        .order_by(CalendarConnection.created_date)
    )
    connections = result.scalars().all()

    events: list[CalendarEventRead] = []
    errors: list[str] = []
    for connection in connections:
        fetch_error = await refresh_connection(connection, fetcher)
        if fetch_error:
            errors.append(f"{connection.name}: {fetch_error}")

        if connection.cached_ics is None:
            continue
        try:
            # One fetch/cache refresh per connection above; expanding the
            # window is parse-only and cheap
            for day_offset in range(days):
                events.extend(
                    parse_events(
                        connection.cached_ics,
                        connection,
                        target_date + timedelta(days=day_offset),
                        tz=zone,
                    )
                )
        except ValueError as exc:
            errors.append(f"{connection.name}: {exc}")

    # Persist whatever cache-column updates refresh_connection made
    await db.commit()

    # By day, then all-day events first, then timed events by start;
    # timestamp() keeps naive and timezone-aware starts comparable
    events.sort(key=lambda e: (e.event_date, not e.all_day, e.start.timestamp()))

    return CalendarEventList(events=events, date=target_date, errors=errors)


@router.get("/{connection_id}", summary="Get a calendar connection by ID")
async def read_calendar_connection(
    connection_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CalendarConnectionRead:
    """
    Retrieve a specific calendar connection by its ID.

    - **connection_id**: The unique identifier of the connection to retrieve
    """
    connection = await _get_connection_and_authorize(db, connection_id, current_user)
    return CalendarConnectionRead.model_validate(connection)


@router.patch(
    "/{connection_id}", summary="Update a calendar connection (partial update)"
)
async def patch_calendar_connection(
    connection_id: int,
    connection_update: CalendarConnectionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CalendarConnectionRead:
    """
    Update specific fields of a calendar connection. Only provided fields are
    updated. Changing **url** clears the cached feed so the next events call
    fetches the new address.

    You can update any combination of these fields:
    - **name**: Display name for the calendar
    - **color**: Hex color code for the calendar's events
    - **url**: The ICS feed URL (http:// or https://)
    - **provider**: Optional free-form label
    - **enabled**: Whether the calendar's events are included
    """
    db_connection = await _get_connection_and_authorize(db, connection_id, current_user)

    connection_data = connection_update.model_dump(exclude_unset=True)

    new_url = connection_data.get("url")
    if new_url is not None and new_url != db_connection.url:
        # The cache belongs to the old URL - drop it so the next events call
        # fetches the new feed from scratch
        db_connection.cached_ics = None
        db_connection.etag = None
        db_connection.last_fetched_at = None
        db_connection.last_error = None

    for key, value in connection_data.items():
        setattr(db_connection, key, value)
    db_connection.updated_date = datetime.now()  # server-stamped, never client-set
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Calendar connection change violates a database constraint",
        )
    await db.refresh(db_connection)

    return CalendarConnectionRead.model_validate(db_connection)


@router.delete("/{connection_id}", summary="Delete a calendar connection")
async def delete_calendar_connection(
    connection_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a calendar connection by its ID. This only removes the
    subscription; the remote calendar is never modified.

    - **connection_id**: The unique identifier of the connection to delete
    """
    db_connection = await _get_connection_and_authorize(db, connection_id, current_user)

    await db.delete(db_connection)
    await db.commit()
    return JSONResponse(
        content={"detail": "Calendar connection deleted successfully"}
    )
