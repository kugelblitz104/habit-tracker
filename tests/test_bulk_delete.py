"""Cross-cutting auth/validation for the profile-scoped bulk-delete endpoints.

Each of projects / tasks / countdowns / time-entries / habits / trackers
exposes a ``DELETE /?profile_id=`` that removes every row in one profile.
This file keeps only ``TestBulkDeleteAuth``, the parametrized check that
spans all six paths at once; the per-entity delete behavior (what actually
gets removed/cascaded/unlinked) lives with the rest of that entity's CRUD
tests - see ``TestDeleteAll<Entity>`` in test_projects.py, test_tasks.py,
test_countdowns.py, test_time_entries.py, test_habits.py, and
test_trackers.py.
"""

from tests.factories import ProfileFactory, UserFactory

BULK_DELETE_PATHS = (
    "/projects/",
    "/tasks/",
    "/countdowns/",
    "/time-entries/",
    "/habits/",
    "/trackers/",
)


class TestBulkDeleteAuth:
    """Auth/validation shared across every bulk-delete endpoint."""

    async def test_requires_profile_id(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        for path in BULK_DELETE_PATHS:
            response = await client.delete(path)
            assert response.status_code == 422, path

    async def test_foreign_profile_forbidden(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        for path in BULK_DELETE_PATHS:
            response = await client.delete(path, params={"profile_id": foreign.id})
            assert response.status_code == 403, path

    async def test_unknown_profile_not_found(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        for path in BULK_DELETE_PATHS:
            response = await client.delete(path, params={"profile_id": 99999})
            assert response.status_code == 404, path
