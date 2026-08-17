"""Tests for user management endpoints."""

from sqlalchemy import select

from habit_tracker.schemas.db_models import Habit, Tracker, User
from tests.factories import AdminUserFactory, HabitFactory, TrackerFactory, UserFactory


class TestGetUser:
    """Tests for GET /users/{user_id} endpoint."""

    async def test_get_own_user(self, client, db_session, login_as):
        """User can retrieve their own profile."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user.id
        assert data["username"] == user.username
        assert data["email"] == user.email

    async def test_get_other_user_as_regular(self, client, db_session, login_as):
        """Regular user cannot access other user profiles (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        await login_as(user1)

        # Try to access user2's profile
        response = await client.get(f"/users/{user2.id}")
        assert response.status_code == 403

    async def test_get_other_user_as_admin(self, client, db_session, login_as):
        """Admin can access any user profile."""
        admin = AdminUserFactory()
        regular_user = UserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        # Access regular user's profile
        response = await client.get(f"/users/{regular_user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == regular_user.id

    async def test_get_nonexistent_user(self, client, db_session, login_as):
        """Return 404 for non-existent user."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.get("/users/99999")
        assert response.status_code == 404

    async def test_get_user_without_auth(self, client, db_session):
        """Reject request without authentication token (401)."""
        user = UserFactory()
        await db_session.commit()

        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 401


class TestListUsers:
    """Tests for GET /users/ endpoint."""

    async def test_list_users_as_regular_user(self, client, db_session, login_as):
        """Regular user sees only themselves."""
        user1 = UserFactory()
        UserFactory()
        await db_session.commit()

        # Login as user1
        await login_as(user1)

        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["users"]) == 1
        assert data["users"][0]["id"] == user1.id

    async def test_list_users_as_admin(self, client, db_session, login_as):
        """Admin sees all users."""
        admin = AdminUserFactory()
        UserFactory()
        UserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3  # admin + 2 users

    async def test_list_users_pagination(self, client, db_session, login_as):
        """Verify pagination with limit parameter."""
        admin = AdminUserFactory()
        for _ in range(10):
            UserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.get("/users/?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["users"]) == 3
        assert data["total"] == 11  # admin + 10 users
        assert data["limit"] == 3

    async def test_list_users_default_limit(self, client, db_session, login_as):
        """Verify default limit of 5."""
        admin = AdminUserFactory()
        for _ in range(10):
            UserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert len(data["users"]) == 5

    async def test_list_users_max_limit(self, client, db_session, login_as):
        """Verify max limit of 100."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        # Requesting beyond max should be rejected
        response = await client.get("/users/?limit=101")
        assert response.status_code == 422  # Validation error

    async def test_list_users_returns_total_count(self, client, db_session, login_as):
        """Verify total count in response."""
        admin = AdminUserFactory()
        for _ in range(7):
            UserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.get("/users/?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 8  # admin + 7 users
        assert len(data["users"]) == 3

    async def test_list_users_offset_skips_as_admin(self, client, db_session, login_as):
        """offset skips users without changing total."""
        admin = AdminUserFactory()
        for _ in range(4):
            UserFactory()
        await db_session.commit()

        await login_as(admin)

        first = await client.get("/users/?limit=2&offset=0")
        second = await client.get("/users/?limit=2&offset=2")
        assert first.status_code == 200
        assert second.status_code == 200

        first_ids = [u["id"] for u in first.json()["users"]]
        second_ids = [u["id"] for u in second.json()["users"]]
        assert len(second_ids) == 2
        assert set(first_ids).isdisjoint(second_ids)
        assert first.json()["total"] == 5
        assert second.json()["offset"] == 2

    async def test_list_users_two_page_walk_covers_every_user_once(
        self, client, db_session, login_as
    ):
        """Walking two pages by offset returns each user exactly once, proving
        the list is ordered rather than left to Postgres's incidental order."""
        admin = AdminUserFactory()
        others = [UserFactory() for _ in range(4)]
        await db_session.commit()
        expected_ids = {admin.id, *(u.id for u in others)}

        await login_as(admin)

        first = await client.get("/users/?limit=3&offset=0")
        second = await client.get("/users/?limit=3&offset=3")
        assert first.status_code == 200
        assert second.status_code == 200

        first_ids = [u["id"] for u in first.json()["users"]]
        second_ids = [u["id"] for u in second.json()["users"]]
        walked_ids = first_ids + second_ids
        assert len(walked_ids) == len(set(walked_ids))
        assert set(walked_ids) == expected_ids

    async def test_list_users_offset_ignored_for_regular_user(
        self, client, db_session, login_as
    ):
        """A regular user always sees exactly themselves, offset or not."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/users/?offset=5")
        assert response.status_code == 200
        data = response.json()
        assert [u["id"] for u in data["users"]] == [user.id]
        assert data["total"] == 1


class TestUpdateUserPut:
    """Tests for PUT /users/{user_id} endpoint."""

    async def test_update_own_user_put(self, client, db_session, login_as):
        """User can update their own profile (full update)."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": "updateduser",
                "first_name": "Updated",
                "last_name": "User",
                "email": "updated@example.com",
                "plaintext_password": "newpassword123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "updateduser"
        assert data["first_name"] == "Updated"
        assert data["last_name"] == "User"
        assert data["email"] == "updated@example.com"

    async def test_update_other_user_as_regular_put(self, client, db_session, login_as):
        """Regular user cannot update other profiles (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        await login_as(user1)

        # Try to update user2's profile
        response = await client.put(
            f"/users/{user2.id}",
            json={
                "username": "hacked",
                "first_name": "Hacked",
                "last_name": "User",
                "email": "hacked@example.com",
                "plaintext_password": "hackedpassword123",
            },
        )
        assert response.status_code == 403

    async def test_update_user_as_admin_put(self, client, db_session, login_as):
        """Admin can update any user profile."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": "adminupdated",
                "first_name": "Admin",
                "last_name": "Updated",
                "email": "adminupdated@example.com",
                "plaintext_password": "adminnewpass",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "adminupdated"

    async def test_update_user_all_fields_put(self, client, db_session, login_as):
        """Verify all fields are updated."""
        user = UserFactory(
            username="original",
            first_name="Original",
            last_name="Name",
            email="original@example.com",
        )
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": "newusername",
                "first_name": "New",
                "last_name": "Name",
                "email": "new@example.com",
                "plaintext_password": "newpassword456",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newusername"
        assert data["first_name"] == "New"
        assert data["last_name"] == "Name"
        assert data["email"] == "new@example.com"

    async def test_update_nonexistent_user_put(self, client, db_session, login_as):
        """Return 404 for non-existent user."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.put(
            "/users/99999",
            json={
                "username": "nonexistent",
                "first_name": "Non",
                "last_name": "Existent",
                "email": "nonexistent@example.com",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 404

    async def test_update_user_password(self, client, db_session, login_as):
        """Verify password is updated correctly."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        new_password = "updatedpassword789"
        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "plaintext_password": new_password,
            },
        )
        assert response.status_code == 200

        # Attempt to login with new password
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": new_password},
        )
        assert login_response.status_code == 200


class TestUpdateUserPatch:
    """Tests for PATCH /users/{user_id} endpoint."""

    async def test_update_own_user_patch(self, client, db_session, login_as):
        """User can partially update their profile."""
        user = UserFactory(username="patchuser", first_name="Original")
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "Patched"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Patched"
        assert data["username"] == "patchuser"  # Unchanged

    async def test_update_user_single_field_patch(self, client, db_session, login_as):
        """Update only one field."""
        user = UserFactory()
        original_username = user.username
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "SingleFieldUpdate"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "SingleFieldUpdate"
        assert data["username"] == original_username

    async def test_update_user_multiple_fields_patch(
        self, client, db_session, login_as
    ):
        """Update multiple fields."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "Multi", "last_name": "Update"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Multi"
        assert data["last_name"] == "Update"

    async def test_update_user_username_patch(self, client, db_session, login_as):
        """Update username."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"username": "newusernamepatched"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newusernamepatched"

    async def test_update_user_email_patch(self, client, db_session, login_as):
        """Update email."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"email": "newemail@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "newemail@example.com"

    async def test_update_user_names_patch(self, client, db_session, login_as):
        """Update first and last name."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "NewFirst", "last_name": "NewLast"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "NewFirst"
        assert data["last_name"] == "NewLast"

    async def test_update_user_password_patch(self, client, db_session, login_as):
        """Verify password can be updated via PATCH."""
        user = UserFactory()
        await db_session.commit()

        # Login
        await login_as(user)

        new_password = "newpatchpassword789"
        response = await client.patch(
            f"/users/{user.id}",
            json={"plaintext_password": new_password},
        )
        assert response.status_code == 200

        # Attempt to login with new password
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": new_password},
        )
        assert login_response.status_code == 200

    async def test_update_other_user_as_regular_patch(
        self, client, db_session, login_as
    ):
        """Regular user cannot update others (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        await login_as(user1)

        # Try to update user2
        response = await client.patch(
            f"/users/{user2.id}",
            json={"first_name": "Hacked"},
        )
        assert response.status_code == 403


class TestDeleteUser:
    """Tests for DELETE /users/{user_id} endpoint."""

    async def test_delete_own_user(self, client, db_session, login_as):
        """User can delete their own account."""
        user = UserFactory()
        await db_session.commit()
        user_id = user.id

        # Login
        await login_as(user)

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify user was deleted
        result = await db_session.execute(select(User).filter(User.id == user_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_as_regular(self, client, db_session, login_as):
        """Regular user cannot delete other accounts (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        await login_as(user1)

        # Try to delete user2
        response = await client.delete(f"/users/{user2.id}")
        assert response.status_code == 403

    async def test_delete_user_as_admin(self, client, db_session, login_as):
        """Admin can delete any user account."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()
        user_id = user.id

        # Login as admin
        await login_as(admin)

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify user was deleted
        result = await db_session.execute(select(User).filter(User.id == user_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_nonexistent_user(self, client, db_session, login_as):
        """Return 404 for non-existent user."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        await login_as(admin)

        response = await client.delete("/users/99999")
        assert response.status_code == 404

    async def test_delete_user_cascades_to_habits(self, client, db_session, login_as):
        """Verify habits are deleted with user."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        user_id = user.id
        habit_id = habit.id

        # Login
        await login_as(user)

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify habit was also deleted
        result = await db_session.execute(select(Habit).filter(Habit.id == habit_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_user_cascades_to_trackers(self, client, db_session, login_as):
        """Verify trackers are deleted with user."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        user_id = user.id
        tracker_id = tracker.id

        # Login
        await login_as(user)

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify tracker was also deleted
        result = await db_session.execute(
            select(Tracker).filter(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None


class TestRetiredUserHabitsRoute:
    """The user-scoped habit list was replaced by GET /habits/?profile_id=."""

    async def test_user_habits_route_is_gone(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 404
