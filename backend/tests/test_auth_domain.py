import os
from uuid import uuid4
import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

USER_UUID = str(uuid4())


def make_jwt(email: str, sub: str = USER_UUID) -> str:
    return jwt.encode({"sub": sub, "email": email}, "secret", algorithm="HS256")


@pytest.mark.asyncio
async def test_dev_mode_normal_email_allowed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAIN", "")

    token = make_jwt("student@gmail.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/bookings/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["ok"] is True


@pytest.mark.asyncio
async def test_dev_mode_another_email_allowed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAIN", "")

    token = make_jwt("user@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/bookings/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["ok"] is True


@pytest.mark.asyncio
async def test_prod_mode_iitg_email_allowed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAIN", "iitg.ac.in")

    token = make_jwt("student@iitg.ac.in")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/bookings/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["ok"] is True


@pytest.mark.asyncio
async def test_prod_mode_non_iitg_email_rejected(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAIN", "iitg.ac.in")

    token = make_jwt("student@gmail.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/bookings/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_unverified_invalid_token_rejected(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/bookings/me", headers={"Authorization": "Bearer invalid.jwt.token"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_prod_mode_x_user_id_rejected(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/bookings/me", headers={"X-User-ID": USER_UUID})
        assert res.status_code == 401
