"""Name -> URL-slug conversion, and collision-free slug allocation.

Detail URLs read as the thing they open - `/tasks/setup-utilities`,
`/projects/alpha-project`, `/habits/daily-habit` - rather than carrying a
numeric id. Slugs are **stored**, not derived on read, which is what makes the
numbered suffixes stable: `follow-up-2` keeps that slug for life, so deleting
the `follow-up` that came before it does not silently re-point it. A slug is
(re)allocated on create and whenever its source text changes.

Every `slug` column is NOT NULL, mirroring the column it derives from
(`Task.title`, `Project.name`, `Habit.name`, all NOT NULL): a slug is a
function of that text, so a row that has the text has a slug. `slugify`
therefore always returns one - see `FALLBACK_BASE` for the two inputs that
can't produce a slug directly.

Nothing here imports an ORM model: the helpers take the model class, so adding
a slug to another entity needs no change in this module.
"""

import re
import unicodedata
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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


def slugify(source: str) -> str:
    """Reduce a title or name to a lowercase hyphen-separated URL segment.

    Accents fold to ASCII ("Café" -> "cafe"), every run of non-alphanumerics
    collapses to one hyphen, and the result is trimmed to `MAX_SLUG_LENGTH`
    without splitting a word.

    Always returns a usable slug. Two inputs can't produce one from their own
    characters and fall back to `FALLBACK_BASE`:

    - **Nothing survives folding** - "???", or text written entirely in a
      non-Latin script, since ASCII folding drops those code points. Becomes
      "task".
    - **The result is all digits** - "2841" would otherwise slugify to "2841",
      and `/tasks/2841` is indistinguishable from the numeric id route, so it
      would open a *different* row. Becomes "task-2841", which keeps the
      source's information while breaking the ambiguity.

    Trimming happens BEFORE those two checks, because trimming can create them:
    "2841 supercalifragilistic..." is not all digits until its tail is cut off.
    """
    folded = unicodedata.normalize("NFKD", source)
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

    Split out from `allocate_slug` so the numbering rule is testable
    without a database.
    """
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


async def allocate_slug(
    db: AsyncSession,
    model: type,
    *,
    profile_id: int,
    source: str,
    exclude_id: int | None = None,
) -> str:
    """Pick an unused slug for `source` among `model`'s rows in `profile_id`.

    `model` is any ORM class with `slug`, `profile_id` and `id` columns (Task,
    Project, Habit). Typed `type` rather than a union, matching
    `core/http.bulk_delete_in_profile` - the alternative is a growing union that
    every new slugged entity has to be added to.

    Slugs are unique per profile **per entity**: a project and a task may both
    be `alpha`, since they resolve through different endpoints. The same name in
    two profiles also keeps the clean slug in both. `exclude_id` leaves a row out
    of the collision set so re-slugging on rename doesn't count the row's own
    current slug and bump it to "-2".

    Uniqueness is enforced here rather than by a DB constraint: the column is
    indexed but not unique, so two creates racing on the same name can end up
    sharing a slug. That is preferred over the alternative, where losing the race
    fails the create outright - a duplicate slug costs one row its pretty URL
    (`get_by_slug` returns the lowest id) and nothing more.
    """
    base = slugify(source)

    # `base` is [a-z0-9-] only, so it carries no LIKE wildcards to escape.
    query = select(model.slug).filter(
        model.profile_id == profile_id,
        or_(model.slug == base, model.slug.like(f"{base}-%")),
    )
    if exclude_id is not None:
        query = query.filter(model.id != exclude_id)
    result = await db.execute(query)
    taken = set(result.scalars().all())

    return next_free_slug(base, taken)


async def get_by_slug(
    db: AsyncSession,
    model: type,
    *,
    profile_id: int,
    slug: str,
) -> Any | None:
    """The `model` row in `profile_id` with this slug, or None.

    Deliberately does NOT authorize or raise: callers authorize the profile
    first and raise their own entity-specific 404 detail ("Task not found" vs
    "Project not found"), matching how the rest of each router reads.

    Lowest id wins. Slugs are allocated to be unique per profile but the
    allocation is not constraint-enforced, so a duplicate is possible and has to
    resolve deterministically rather than arbitrarily.
    """
    result = await db.execute(
        select(model)
        .filter(model.profile_id == profile_id, model.slug == slug)
        .order_by(model.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
