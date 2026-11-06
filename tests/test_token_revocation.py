"""Token-version revocation: logout, password change and the `ver` claim."""

from datetime import UTC, datetime, timedelta

import jwt

from habit_tracker.core.config import settings
from habit_tracker.core.security import create_reset_token
from tests.factories import UserFactory


async def _login(client, user):
    response = await client.post(
        "/auth/login", data={"username": user.username, "password": "password123"}
    )
    assert response.status_code == 200
    return response.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _legacy_token(user, token_type):
    """A token as issued before the `ver` claim existed."""
    return jwt.encode(
        {
            "sub": str(user.id),
            "type": token_type,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


async def _refresh(client, token):
    return await client.post("/auth/refresh", json={"refresh_token": token})


class TestLogout:
    async def test_logout_revokes_refresh_token(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)

        out = await client.post("/auth/logout", headers=_bearer(tokens["access_token"]))
        assert out.status_code == 200
        assert "message" in out.json()

        assert (await _refresh(client, tokens["refresh_token"])).status_code == 401

    async def test_logout_revokes_access_token(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)
        headers = _bearer(tokens["access_token"])

        assert (await client.post("/auth/logout", headers=headers)).status_code == 200
        assert (await client.get("/profiles/", headers=headers)).status_code == 401

    async def test_logout_requires_token(self, client):
        assert (await client.post("/auth/logout")).status_code == 401

    async def test_login_after_logout_issues_working_pair(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        old = await _login(client, user)
        await client.post("/auth/logout", headers=_bearer(old["access_token"]))

        new = await _login(client, user)
        assert (
            await client.get("/profiles/", headers=_bearer(new["access_token"]))
        ).status_code == 200
        assert (await _refresh(client, new["refresh_token"])).status_code == 200

    async def test_refresh_still_rotates(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)

        rotated = await _refresh(client, tokens["refresh_token"])
        assert rotated.status_code == 200
        assert (
            await client.get(
                "/profiles/", headers=_bearer(rotated.json()["access_token"])
            )
        ).status_code == 200


class TestVersionClaim:
    async def test_token_without_ver_accepted_for_version_zero(
        self, client, db_session
    ):
        user = UserFactory()
        await db_session.commit()

        assert (
            await client.get(
                "/profiles/", headers=_bearer(_legacy_token(user, "access"))
            )
        ).status_code == 200
        assert (
            await _refresh(client, _legacy_token(user, "refresh"))
        ).status_code == 200

    async def test_token_without_ver_rejected_after_bump(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)
        await client.post("/auth/logout", headers=_bearer(tokens["access_token"]))

        assert (
            await client.get(
                "/profiles/", headers=_bearer(_legacy_token(user, "access"))
            )
        ).status_code == 401
        assert (
            await _refresh(client, _legacy_token(user, "refresh"))
        ).status_code == 401


class TestPasswordChangeRevokes:
    async def test_reset_password_revokes_refresh_token(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)

        reset = await client.post(
            "/auth/reset-password",
            json={
                "token": create_reset_token(data={"sub": str(user.id)}),
                "new_password": "brandnewpassword1",
            },
        )
        assert reset.status_code == 200
        assert (await _refresh(client, tokens["refresh_token"])).status_code == 401

    async def test_user_put_password_revokes_tokens(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)
        headers = _bearer(tokens["access_token"])

        response = await client.patch(
            f"/users/{user.id}",
            json={"plaintext_password": "brandnewpassword1"},
            headers=headers,
        )
        assert response.status_code == 200
        assert (await _refresh(client, tokens["refresh_token"])).status_code == 401
        assert (await client.get("/profiles/", headers=headers)).status_code == 401

    async def test_user_patch_without_password_keeps_tokens(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        tokens = await _login(client, user)

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "Renamed"},
            headers=_bearer(tokens["access_token"]),
        )
        assert response.status_code == 200
        assert (await _refresh(client, tokens["refresh_token"])).status_code == 200
