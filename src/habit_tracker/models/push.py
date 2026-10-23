from pydantic import BaseModel, field_validator

from habit_tracker.models._validators import (
    non_blank_string,
    validate_push_auth,
    validate_push_endpoint,
    validate_push_p256dh,
)


class PushSubscriptionDelete(BaseModel):
    profile_id: int
    endpoint: str

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        return validate_push_endpoint(non_blank_string(v, "Endpoint"))


class PushSubscriptionCreate(PushSubscriptionDelete):
    p256dh: str
    auth: str

    @field_validator("p256dh")
    @classmethod
    def validate_p256dh(cls, v: str) -> str:
        return validate_push_p256dh(non_blank_string(v, "Key"))

    @field_validator("auth")
    @classmethod
    def validate_auth(cls, v: str) -> str:
        return validate_push_auth(non_blank_string(v, "Key"))


class PushTest(BaseModel):
    profile_id: int


class VapidPublicKey(BaseModel):
    public_key: str
