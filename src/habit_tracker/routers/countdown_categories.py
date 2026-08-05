from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_child,
    get_owned_profile,
)
from habit_tracker.core.http import bulk_delete_in_profile, integrity_conflict
from habit_tracker.models import (
    CountdownCategoryCreate,
    CountdownCategoryList,
    CountdownCategoryRead,
    CountdownCategoryUpdate,
)
from habit_tracker.schemas.db_models import Countdown, CountdownCategory, User

router = APIRouter(
    prefix="/countdown-categories",
    tags=["countdown-categories"],
    responses={404: {"description": "Not found"}},
)


async def _get_category_and_authorize(
    db: AsyncSession, category_id: int, current_user: User
) -> CountdownCategory:
    category, _ = await get_owned_child(
        db,
        CountdownCategory,
        category_id,
        current_user,
        not_found_detail="Countdown category not found",
        resource_name="countdown category",
    )
    return category


@router.get("/", summary="List countdown categories for a profile")
async def list_countdown_categories(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(
        description="The profile whose countdown categories to list"
    ),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CountdownCategoryList:
    """List a profile's countdown categories, ordered by name.

    Includes categories with no countdowns: a group's colour outlives its members,
    so a category emptied and later refilled keeps the colour it was given. The
    grouped views only render categories that have a countdown in range.
    """
    await get_owned_profile(db, profile_id, current_user, "countdown category")

    query = select(CountdownCategory).filter(CountdownCategory.profile_id == profile_id)
    result = await db.execute(
        query.order_by(CountdownCategory.name).limit(limit).offset(offset)
    )
    categories = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(CountdownCategory.profile_id == profile_id)
    )
    total = count_result.scalar() or 0

    return CountdownCategoryList(
        categories=[CountdownCategoryRead.model_validate(c) for c in categories],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/", status_code=status.HTTP_201_CREATED, summary="Create a countdown category"
)
async def create_countdown_category(
    category: CountdownCategoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownCategoryRead:
    """Create a countdown category.

    - **profile_id**: The profile this category belongs to
    - **name**: The category's name, unique within the profile
    - **color**: Optional hex colour for the group

    Fails with 409 if a category with this name already exists in the profile.
    """
    await get_owned_profile(db, category.profile_id, current_user, "countdown category")

    db_category = CountdownCategory(**category.model_dump())
    db.add(db_category)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise integrity_conflict(
            "A countdown category with this name already exists in this profile"
        )
    await db.refresh(db_category)
    return CountdownCategoryRead.model_validate(db_category)


@router.get("/{category_id}", summary="Get a countdown category by ID")
async def read_countdown_category(
    category_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownCategoryRead:
    category = await _get_category_and_authorize(db, category_id, current_user)
    return CountdownCategoryRead.model_validate(category)


@router.patch("/{category_id}", summary="Update a countdown category (partial update)")
async def patch_countdown_category(
    category_id: int,
    category_update: CountdownCategoryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownCategoryRead:
    """Update a countdown category. Only provided fields are updated.

    Renaming updates every countdown currently in this category so their
    **category** text keeps matching the record's new name. Setting **color**
    to null clears it; setting **name** to null is rejected.

    Fails with 409 if the new name is already used by another category in the
    same profile.
    """
    db_category = await _get_category_and_authorize(db, category_id, current_user)

    data = category_update.model_dump(exclude_unset=True)
    previous_name = db_category.name
    for key, value in data.items():
        setattr(db_category, key, value)
    db_category.updated_date = datetime.now()  # server-stamped, never client-set

    try:
        # Keep Countdown.category in step with the record it mirrors. One
        # UPDATE, not a row-at-a-time loop. This runs inside the try block
        # because it triggers autoflush of the renamed db_category, so a
        # duplicate name surfaces its IntegrityError here rather than at
        # commit.
        if db_category.name != previous_name:
            await db.execute(
                update(Countdown)
                .where(Countdown.category_id == db_category.id)
                .values(category=db_category.name)
            )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise integrity_conflict(
            "A countdown category with this name already exists in this profile"
        )
    await db.refresh(db_category)
    return CountdownCategoryRead.model_validate(db_category)


@router.delete("/", summary="Delete all countdown categories in a profile")
async def delete_all_countdown_categories(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(
        description="The profile whose countdown categories to delete"
    ),
) -> JSONResponse:
    """
    Delete every countdown category in a profile.

    - **profile_id**: The profile whose countdown categories to delete (required)

    This action cannot be undone. Countdowns that were in a deleted category
    are kept and become uncategorised.
    """
    # Authorize before mutating anything: bulk_delete_in_profile checks
    # ownership too, but that happens after the UPDATE below, so an
    # unauthorized caller must be rejected here first.
    await get_owned_profile(db, profile_id, current_user, "countdown category")

    # Clearing the text mirror as well as the FK means the countdowns actually
    # leave their groups instead of rendering under a name with no record.
    await db.execute(
        update(Countdown)
        .where(Countdown.profile_id == profile_id)
        .where(Countdown.category_id.is_not(None))
        .values(category=None, category_id=None)
    )
    return await bulk_delete_in_profile(
        db,
        CountdownCategory,
        profile_id,
        current_user,
        resource_name="countdown category",
        detail="Deleted {count} countdown categories; their countdowns were kept and uncategorised",
    )


@router.delete("/{category_id}", summary="Delete a countdown category")
async def delete_countdown_category(
    category_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a countdown category by its ID.

    This action cannot be undone. Countdowns in the category are kept and
    become uncategorised.
    """
    db_category = await _get_category_and_authorize(db, category_id, current_user)
    await db.execute(
        update(Countdown)
        .where(Countdown.category_id == category_id)
        .values(category=None, category_id=None)
    )
    await db.delete(db_category)
    await db.commit()
    return JSONResponse(
        content={
            "detail": "Countdown category deleted successfully; "
            "its countdowns were kept and uncategorised"
        }
    )
