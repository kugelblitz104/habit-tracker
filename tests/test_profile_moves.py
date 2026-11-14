"""Unit tests of `services/profile_moves.py` called with a session.

What travels with a move is tested through the API in `test_tasks.py` and
`test_projects.py`; this file covers the owner check, and slug allocation
under the app's `autoflush=False`, which the test sessions do not share.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from habit_tracker.schemas.db_models import Task
from habit_tracker.services.profile_moves import move_project_contents, target_profile
from tests.factories import ProfileFactory, ProjectFactory, TaskFactory, UserFactory


class TestMoveProjectContents:
    async def test_tasks_sharing_a_title_get_distinct_slugs_without_autoflush(
        self, db_session
    ):
        user = UserFactory()
        profile = ProfileFactory(user=user)
        other = ProfileFactory(user=user)
        project = ProjectFactory(profile=profile)
        TaskFactory(profile=profile, project=project, title="Follow up")
        TaskFactory(profile=profile, project=project, title="Follow up")
        await db_session.commit()

        with db_session.no_autoflush:
            await move_project_contents(db_session, project.id, other.id)
            await db_session.flush()
            slugs = (
                await db_session.scalars(
                    select(Task.slug).where(Task.profile_id == other.id)
                )
            ).all()
        assert sorted(slugs) == ["follow-up", "follow-up-2"]


class TestTargetProfile:
    async def test_no_move_returns_none(self, db_session):
        """An omitted profile_id or the current one is not a move."""
        profile = ProfileFactory()
        await db_session.commit()

        assert await target_profile(db_session, profile, None) is None
        assert await target_profile(db_session, profile, profile.id) is None

    async def test_returns_the_same_users_profile(self, db_session):
        user = UserFactory()
        profile = ProfileFactory(user=user)
        other = ProfileFactory(user=user)
        await db_session.commit()

        assert await target_profile(db_session, profile, other.id) is other

    @pytest.mark.parametrize("foreign", [True, False])
    async def test_rejects_missing_or_foreign_profile(self, db_session, foreign):
        profile = ProfileFactory()
        stranger = ProfileFactory()
        await db_session.commit()
        new_id = stranger.id if foreign else 999999

        with pytest.raises(HTTPException) as exc_info:
            await target_profile(db_session, profile, new_id)
        assert exc_info.value.status_code == 400
        assert (
            exc_info.value.detail
            == "New profile not found or does not belong to the same user"
        )
