"""Unit tests of the plain helpers in core/route_helpers.py, run against
db_session directly rather than through an endpoint."""

from sqlalchemy import select

from habit_tracker.core.route_helpers import paged
from habit_tracker.schemas.db_models import Project
from tests.factories import ProfileFactory, ProjectFactory, UserFactory


class TestPaged:
    async def _seed(self, db_session):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Paged")
        other = ProfileFactory(user=user, name="Other")
        projects = [ProjectFactory(profile=profile) for _ in range(5)]
        ProjectFactory(profile=other)
        ProjectFactory(profile=profile, archived=True)
        await db_session.commit()
        return profile, sorted(p.id for p in projects)

    def _live(self, profile):
        return (
            select(Project)
            .filter(Project.profile_id == profile.id, Project.archived.is_(False))
            .order_by(Project.id)
        )

    async def test_total_is_the_filtered_count_whatever_the_page(self, db_session):
        profile, ids = await self._seed(db_session)

        for offset in (0, 2, 4):
            result, total = await paged(
                db_session, self._live(profile), limit=2, offset=offset
            )
            assert [p.id for p in result.scalars()] == ids[offset : offset + 2]
            assert total == 5

    async def test_offset_past_the_end_returns_no_rows(self, db_session):
        profile, _ = await self._seed(db_session)

        result, total = await paged(db_session, self._live(profile), limit=2, offset=50)

        assert result.scalars().all() == []
        assert total == 5

    async def test_multi_column_select(self, db_session):
        profile, ids = await self._seed(db_session)
        stmt = (
            select(Project.id, Project.name)
            .filter(Project.profile_id == profile.id, Project.archived.is_(False))
            .order_by(Project.id.desc())
        )

        result, total = await paged(db_session, stmt, limit=3, offset=1)

        assert [row.id for row in result.all()] == ids[::-1][1:4]
        assert total == 5
