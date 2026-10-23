from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core import rate_limit
from habit_tracker.core.dependencies import get_current_user, get_db, get_owned_profile
from habit_tracker.models import (
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushTest,
    VapidPublicKey,
)
from habit_tracker.schemas.db_models import PushSubscription, User
from habit_tracker.services import notifications, web_push

router = APIRouter(
    prefix="/push",
    tags=["push"],
    responses={404: {"description": "Not found"}},
)


def _require_vapid() -> None:
    if not web_push.is_configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Web Push is not configured on this server",
        )


@router.get("/vapid-public-key", summary="Get the server's VAPID public key")
async def get_vapid_public_key() -> VapidPublicKey:
    """The key a browser passes as `applicationServerKey` when subscribing.

    Returns 404 when the server has no VAPID key and subject, which means
    notifications are unavailable and clients should hide the feature.
    """
    _require_vapid()
    return VapidPublicKey(public_key=web_push.vapid_public_key())


@router.post(
    "/subscriptions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Register a browser for a profile's notifications",
)
async def subscribe(
    body: PushSubscriptionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Save a browser's push subscription for a profile.

    Registering an endpoint the profile already has replaces its keys, so a
    browser that rotated them can call this again. Returns 409 when the profile
    already has the maximum number of other browsers registered.
    """
    await get_owned_profile(db, body.profile_id, current_user, "profile")
    registered = (
        await db.scalars(
            select(PushSubscription.endpoint).where(
                PushSubscription.profile_id == body.profile_id
            )
        )
    ).all()
    limit = notifications.CONFIG["push"]["max_subscriptions_per_profile"]
    if body.endpoint not in registered and len(registered) >= limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A profile can register at most {limit} devices",
        )
    statement = insert(PushSubscription).values(**body.model_dump())
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_push_subscription_profile_endpoint",
            set_={"p256dh": statement.excluded.p256dh, "auth": statement.excluded.auth},
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/subscriptions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a browser from a profile's notifications",
)
async def unsubscribe(
    body: PushSubscriptionDelete,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Delete one browser's subscription. Succeeds when it is already gone."""
    await get_owned_profile(db, body.profile_id, current_user, "profile")
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.profile_id == body.profile_id,
            PushSubscription.endpoint == body.endpoint,
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/test",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit.limit_by_ip("push_test"))],
    summary="Send a test notification to a profile's browsers",
)
async def send_test(
    body: PushTest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Send one notification to every browser registered for the profile.

    Returns 404 when the server has no VAPID key and subject, and 409 when the
    profile has no registered browser. Returns 502 when the push service accepted
    none of the sends. A browser the push service reports gone is unregistered
    either way.
    """
    _require_vapid()
    profile = await get_owned_profile(db, body.profile_id, current_user, "profile")
    registered = await db.scalar(
        select(exists().where(PushSubscription.profile_id == profile.id))
    )
    if not registered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No device is registered for notifications on this profile",
        )
    delivered = await notifications.deliver(
        db,
        web_push.send,
        profile,
        {"title": "Habit Tracker", "body": "Notifications are working", "url": "/"},
    )
    await db.commit()
    if not delivered:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The push service did not accept the notification",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
