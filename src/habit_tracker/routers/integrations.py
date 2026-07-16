from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TaskStatus
from habit_tracker.core.crypto import decrypt_secret, encrypt_secret
from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.models import (
    IntegrationConnectionCreate,
    IntegrationConnectionList,
    IntegrationConnectionRead,
    IntegrationConnectionUpdate,
    IntegrationSyncResult,
    PublishRequest,
    PublishResult,
)
from habit_tracker.schemas.db_models import IntegrationConnection, Task, User
from habit_tracker.services.integrations import (
    ClientBuilder,
    IntegrationError,
    get_client_builder,
)

router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
    responses={404: {"description": "Not found"}},
)


async def _get_connection_and_authorize(
    db: AsyncSession, connection_id: int, current_user: User
) -> IntegrationConnection:
    connection = await db.get(IntegrationConnection, connection_id)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration connection not found",
        )
    await authorize_parent_profile(
        db, connection.profile_id, current_user, "integration connection"
    )
    return connection


@router.get("/", summary="List integration connections for a profile")
async def list_integration_connections(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose connections to list"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> IntegrationConnectionList:
    await get_owned_profile(db, profile_id, current_user, "integration connection")

    result = await db.execute(
        select(IntegrationConnection)
        .filter(IntegrationConnection.profile_id == profile_id)
        .order_by(IntegrationConnection.created_date)
        .limit(limit)
        .offset(offset)
    )
    connections = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(IntegrationConnection.profile_id == profile_id)
    )
    total = count_result.scalar() or 0

    return IntegrationConnectionList(
        integration_connections=[
            IntegrationConnectionRead.model_validate(c) for c in connections
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/", status_code=status.HTTP_201_CREATED, summary="Create an integration connection"
)
async def create_integration_connection(
    connection: IntegrationConnectionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> IntegrationConnectionRead:
    """Connect a profile to Azure DevOps or GitHub with a user-supplied PAT.

    The PAT is encrypted at rest and never returned by the API. Azure DevOps
    requires **organization** + **project**; GitHub optionally takes a
    **default_repo** ("owner/repo") used when publishing.
    """
    await get_owned_profile(db, connection.profile_id, current_user, "integration connection")

    data = connection.model_dump()
    token = data.pop("token")
    db_connection = IntegrationConnection(
        **data, encrypted_token=encrypt_secret(token)
    )
    db.add(db_connection)
    await db.commit()
    await db.refresh(db_connection)
    return IntegrationConnectionRead.model_validate(db_connection)


@router.get("/{connection_id}", summary="Get an integration connection by ID")
async def read_integration_connection(
    connection_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> IntegrationConnectionRead:
    connection = await _get_connection_and_authorize(db, connection_id, current_user)
    return IntegrationConnectionRead.model_validate(connection)


@router.patch("/{connection_id}", summary="Update an integration connection")
async def patch_integration_connection(
    connection_id: int,
    connection_update: IntegrationConnectionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> IntegrationConnectionRead:
    """Partial update. Provide **token** to rotate the PAT; omit it to leave the
    stored one unchanged. Provider is immutable."""
    db_connection = await _get_connection_and_authorize(db, connection_id, current_user)

    update_data = connection_update.model_dump(exclude_unset=True)

    new_token = update_data.pop("token", None)
    if new_token is not None:
        db_connection.encrypted_token = encrypt_secret(new_token)

    for key, value in update_data.items():
        setattr(db_connection, key, value)
    db_connection.updated_date = datetime.now()
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Integration connection change violates a database constraint",
        )
    await db.refresh(db_connection)
    return IntegrationConnectionRead.model_validate(db_connection)


@router.delete("/{connection_id}", summary="Delete an integration connection")
async def delete_integration_connection(
    connection_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    db_connection = await _get_connection_and_authorize(db, connection_id, current_user)
    await db.delete(db_connection)
    await db.commit()
    return JSONResponse(content={"detail": "Integration connection deleted successfully"})


@router.post("/{connection_id}/sync", summary="Pull assigned open items into tasks")
async def sync_integration_connection(
    connection_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    build: Annotated[ClientBuilder, Depends(get_client_builder)],
) -> IntegrationSyncResult:
    """Fetch the current user's open assigned work items / issues and create a
    task for each. Idempotent: an item already imported into this profile is
    skipped (no duplicate), so re-syncing is safe. Imported tasks are not kept
    in sync afterward — this is a one-time pull per item."""
    connection = await _get_connection_and_authorize(db, connection_id, current_user)

    token = decrypt_secret(connection.encrypted_token)
    client = build(connection, token)

    try:
        items = await client.list_open_assigned()
    except IntegrationError as exc:
        connection.last_error = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    imported = 0
    skipped = 0
    details: list[str] = []
    errors: list[str] = []

    for item in items:
        try:
            existing = await db.execute(
                select(Task.id).filter(
                    Task.profile_id == connection.profile_id,
                    Task.source == connection.provider,
                    Task.external_ref == item.external_ref,
                )
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            # Nested savepoint isolates a per-item failure (e.g. a concurrent
            # sync racing on the unique constraint) without discarding the
            # items already imported in this transaction.
            async with db.begin_nested():
                db.add(
                    Task(
                        profile_id=connection.profile_id,
                        title=item.title,
                        notes=item.description,
                        status=TaskStatus.OPEN,
                        source=connection.provider,
                        external_ref=item.external_ref,
                        external_url=item.external_url,
                    )
                )
            imported += 1
            details.append(item.external_ref)
        except IntegrityError:
            # Lost a race — the item now exists.
            skipped += 1
        except Exception as exc:  # noqa: BLE001 - per-item isolation
            errors.append(f"{item.external_ref}: {exc}")

    connection.last_synced_at = datetime.now()
    connection.last_error = None
    await db.commit()

    return IntegrationSyncResult(
        success=True,
        message=f"Imported {imported}, skipped {skipped}.",
        tasks_imported=imported,
        tasks_skipped=skipped,
        details=details,
        errors=errors,
    )


@router.post("/{connection_id}/publish", summary="Publish a task as a new external item")
async def publish_task(
    connection_id: int,
    request: PublishRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    build: Annotated[ClientBuilder, Depends(get_client_builder)],
) -> PublishResult:
    """Create a new work item / issue from a task's title + notes, then link the
    task to it (sets source/external_ref/external_url). One-time create — the
    task's later state is not pushed. Rejects a task that is already linked."""
    connection = await _get_connection_and_authorize(db, connection_id, current_user)

    task = await db.get(Task, request.task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.profile_id != connection.profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task and connection belong to different profiles",
        )
    if task.external_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task is already linked to an external item",
        )

    token = decrypt_secret(connection.encrypted_token)
    client = build(connection, token)

    try:
        item = await client.create_item(task.title, task.notes)
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    task.source = connection.provider
    task.external_ref = item.external_ref
    task.external_url = item.external_url
    task.updated_date = datetime.now()
    await db.commit()

    return PublishResult(
        source=connection.provider,
        external_ref=item.external_ref,
        external_url=item.external_url,
    )
