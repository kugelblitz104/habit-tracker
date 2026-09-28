import logging
import os
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware

from habit_tracker.core.dependencies import get_db
from habit_tracker.routers import (
    auth,
    backup,
    calendar_connections,
    countdown_categories,
    countdowns,
    habits,
    imports,
    integrations,
    journal,
    profiles,
    projects,
    tasks,
    time_entries,
    trackers,
    users,
)

load_dotenv()

# Explicit allowed origins (e.g. the deployed frontend) come from the env var.
# Filter out empty strings so an unset/blank CORS_ORIGINS doesn't become [""],
# which matches no origin and silently blocks every browser request.
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # Allow any localhost / 127.0.0.1 port in development so the Vite dev server
    # works regardless of which port it lands on (5173, 5174, ...). Production
    # origins are still pinned via CORS_ORIGINS above.
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(profiles.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(time_entries.router)
app.include_router(habits.router)
app.include_router(trackers.router)
app.include_router(auth.router)
app.include_router(imports.router)
app.include_router(calendar_connections.router)
app.include_router(integrations.router)
app.include_router(countdown_categories.router)
app.include_router(countdowns.router)
app.include_router(backup.router)
app.include_router(journal.router)


# Kept out of /openapi.json: the front-end generates its client from the schema,
# and a readiness probe is for the orchestrator, not the client.
@app.get("/health", include_in_schema=False)
async def health(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        logger.warning(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from e
    return {"status": "ok"}
