"""Shared plain-function validators used by `@field_validator` stubs across
`models/`.

Deliberately plain functions - no `Annotated`, `AfterValidator`,
`Field(pattern=...)` or `StringConstraints`. Those emit `pattern` /
`maxLength` JSON Schema keywords straight into the generated OpenAPI schema;
a thin `@field_validator` stub that delegates here keeps the schema
untouched.

Every helper here is null-tolerant (`None` passes straight through) unless
its whole purpose is rejecting `None` (`reject_null`). That is what lets one
function serve both a `*Base`/`*Create` model (where the field's own
non-`Optional` annotation already enforces presence) and the corresponding
`*Update` model (where `None` means "field not supplied" - Pydantic already
guarantees a `*Base` field can never actually observe `None` here, since type
validation rejects it before the field validator runs).
"""

import re
from collections.abc import Container
from typing import TypeVar, overload

from pydantic import ValidationInfo

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

T = TypeVar("T")

# The @overload pairs below are type-only (no runtime effect): they tell the
# checker that a concrete `str`/`int` in yields a concrete `str`/`int` out,
# so a `*Base` model's required-field stub (which only ever calls these with
# a non-None value - Pydantic has already rejected `None` by the time the
# validator runs) doesn't need to fight the `Optional` the `*Update` side
# needs. The implementation below each pair is the actual null-tolerant body.


@overload
def validate_hex_color(v: str) -> str: ...
@overload
def validate_hex_color(v: None) -> None: ...
def validate_hex_color(v: str | None) -> str | None:
    if v is not None and not _HEX_COLOR_RE.match(v):
        raise ValueError("Color must be a valid hex code, e.g., #FFFFFF")
    return v


def reject_null(v: object, info: ValidationInfo) -> object:
    # These columns are NOT NULL in the database; omitting a field means
    # "leave unchanged", but an explicit null is always invalid
    if v is None:
        raise ValueError(f"{info.field_name} cannot be null")
    return v


@overload
def non_blank_string(v: str, label: str) -> str: ...
@overload
def non_blank_string(v: None, label: str) -> None: ...
def non_blank_string(v: str | None, label: str) -> str | None:
    if v is not None and not v.strip():
        raise ValueError(f"{label} cannot be empty or whitespace")
    return v


@overload
def trimmed_string(v: str, label: str) -> str: ...
@overload
def trimmed_string(v: None, label: str) -> None: ...
def trimmed_string(v: str | None, label: str) -> str | None:
    """Reject a blank string like `non_blank_string`, then strip it.

    Use where the stored value is matched against a trimmed name elsewhere, so
    that " Bills " and "Bills" cannot become two records for one group.
    """
    if v is None:
        return None
    if not v.strip():
        raise ValueError(f"{label} cannot be empty or whitespace")
    return v.strip()


def non_negative_int(v: int | None, label: str) -> int | None:
    if v is not None and v < 0:
        raise ValueError(f"{label} cannot be negative")
    return v


@overload
def min_value_int(v: int, minimum: int, label: str) -> int: ...
@overload
def min_value_int(v: None, minimum: int, label: str) -> None: ...
def min_value_int(v: int | None, minimum: int, label: str) -> int | None:
    if v is not None and v < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return v


@overload
def validate_membership(
    v: None, valid_values: Container[object], message: str
) -> None: ...
@overload
def validate_membership(v: T, valid_values: Container[T], message: str) -> T: ...
def validate_membership(
    v: T | None, valid_values: Container[T], message: str
) -> T | None:
    if v is not None and v not in valid_values:
        raise ValueError(message)
    return v


def blank_to_none(v: str | None) -> str | None:
    """Normalize a blank/whitespace-only string to `None`; leave others as-is."""
    if v is not None and not v.strip():
        return None
    return v


def validate_owner_repo(v: str) -> str:
    """Validate an already-non-blank, already-stripped "owner/repo" string."""
    parts = v.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError('default_repo must be in the form "owner/repo"')
    return v


def normalize_base_url(v: str | None) -> str | None:
    """Empty/whitespace -> None (public cloud). Otherwise require an http(s)
    scheme and strip any trailing slash so it joins cleanly with the org/project
    path segments."""
    if v is None or not v.strip():
        return None
    v = v.strip().rstrip("/")
    if not v.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    return v


@overload
def non_empty_token(v: str) -> str: ...
@overload
def non_empty_token(v: None) -> None: ...
def non_empty_token(v: str | None) -> str | None:
    if v is not None and not v.strip():
        raise ValueError("token (PAT) cannot be empty")
    return v.strip() if v is not None else v
