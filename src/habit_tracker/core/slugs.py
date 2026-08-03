"""Title -> URL-slug conversion, and collision-free slug allocation.

Task detail URLs are `/tasks/<slug>` rather than `/tasks/<id>`, so a link reads
as the task it opens. Slugs are **stored** (`Task.slug`), not derived on read,
which is what makes the numbered suffixes stable: `follow-up-2` keeps that slug
for life, so deleting the `follow-up` that came before it does not silently
re-point it. A slug is (re)allocated on create and whenever the title changes.

`Task.slug` is NOT NULL, mirroring `Task.title`: a slug is a function of the
title, so if a task has a title it has a slug. `slugify` therefore always
returns one - see `FALLBACK_BASE` for the two titles that can't produce a slug
directly.
"""

import re
import unicodedata

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.schemas.db_models import Task

# Long enough that realistic titles survive whole, short enough to keep URLs
# readable. Trimming happens on a hyphen boundary so a suffix can still fit.
MAX_SLUG_LENGTH = 80

# Stands in when a title cannot produce a slug on its own. Numbering then does
# the rest, so a profile's un-slugifiable titles become `task`, `task-2`, ...
FALLBACK_BASE = "task"

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def _trim(slug: str) -> str:
    """Cut `slug` to `MAX_SLUG_LENGTH` without splitting a word.

    Falls back to a hard cut for a single word longer than the limit, which has
    no hyphen to trim on.
    """
    if len(slug) <= MAX_SLUG_LENGTH:
        return slug
    hard_cut = slug[:MAX_SLUG_LENGTH]
    return hard_cut.rsplit("-", 1)[0].strip("-") or hard_cut


def slugify(title: str) -> str:
    """Reduce a title to a lowercase hyphen-separated URL segment.

    Accents fold to ASCII ("Café" -> "cafe"), every run of non-alphanumerics
    collapses to one hyphen, and the result is trimmed to `MAX_SLUG_LENGTH`
    without splitting a word.

    Always returns a usable slug. Two titles can't produce one from their own
    characters and fall back to `FALLBACK_BASE`:

    - **Nothing survives folding** - "???", or a title written entirely in a
      non-Latin script, since ASCII folding drops those code points. Becomes
      "task".
    - **The result is all digits** - "2841" would otherwise slugify to "2841",
      and `/tasks/2841` is indistinguishable from the numeric id route, so it
      would open a *different* task. Becomes "task-2841", which keeps the
      title's information while breaking the ambiguity.

    Trimming happens BEFORE those two checks, because trimming can create them:
    "2841 supercalifragilistic..." is not all digits until its tail is cut off.
    """
    folded = unicodedata.normalize("NFKD", title)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = _trim(_NON_SLUG_CHARS.sub("-", ascii_only.lower()).strip("-"))

    if not slug:
        return FALLBACK_BASE
    if slug.isdigit():
        # Re-trimmed against the prefix so the result still fits the limit.
        room = MAX_SLUG_LENGTH - len(FALLBACK_BASE) - 1
        return f"{FALLBACK_BASE}-{slug[:room]}"
    return slug


def next_free_slug(base: str, taken: set[str]) -> str:
    """First of `base`, `base-2`, `base-3`, ... that is not in `taken`.

    Split out from `allocate_task_slug` so the numbering rule is testable
    without a database.
    """
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


async def allocate_task_slug(
    db: AsyncSession,
    *,
    profile_id: int,
    title: str,
    exclude_id: int | None = None,
) -> str:
    """Pick an unused slug for `title` within `profile_id`.

    Slugs are unique per profile, so the same title in two profiles keeps the
    clean slug in both. `exclude_id` leaves a task out of the collision set so
    re-slugging on rename doesn't count the task's own current slug and bump
    itself to "-2".

    Uniqueness is enforced here rather than by a DB constraint: the column is
    indexed but not unique, so two creates racing on the same title can end up
    sharing a slug. That is preferred over the alternative, where losing the
    race fails the create outright - a duplicate slug costs one task its pretty
    URL (`read_task_by_slug` returns the lowest id) and nothing more.
    """
    base = slugify(title)

    # `base` is [a-z0-9-] only, so it carries no LIKE wildcards to escape.
    query = select(Task.slug).filter(
        Task.profile_id == profile_id,
        or_(Task.slug == base, Task.slug.like(f"{base}-%")),
    )
    if exclude_id is not None:
        query = query.filter(Task.id != exclude_id)
    result = await db.execute(query)
    taken = set(result.scalars().all())

    return next_free_slug(base, taken)
