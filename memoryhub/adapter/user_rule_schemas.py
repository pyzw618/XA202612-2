"""HTTP contracts for user-defined sensitive-information rules.

These models intentionally do not expose the runtime ``SensitiveRule`` type.
The matcher is accepted as a secret write-only value and is never part of a
response model.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    model_validator,
)


class UserRuleKind(str, Enum):
    """Matcher syntax accepted by the management API."""

    LITERAL = "literal"
    ADVANCED_REGEX = "advanced_regex"


class UserRuleEffect(str, Enum):
    """Observable write-pipeline behavior when a matcher is found."""

    MASK_MATCH = "mask_match"
    DROP_EVENT = "drop_event"


class CreateUserRuleRequest(BaseModel):
    """Create one rule for the caller identity bound by the local gateway."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    label: str = Field(min_length=1, max_length=128)
    kind: UserRuleKind
    effect: UserRuleEffect
    matcher: SecretStr = Field(min_length=1, max_length=2048)
    case_sensitive: StrictBool = False
    enabled: StrictBool = True


class UpdateUserRuleRequest(BaseModel):
    """Optimistically update one rule without ever returning its matcher."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    expected_revision: int = Field(ge=1)
    label: str | None = Field(default=None, min_length=1, max_length=128)
    kind: UserRuleKind | None = None
    effect: UserRuleEffect | None = None
    matcher: SecretStr | None = Field(default=None, min_length=1, max_length=2048)
    case_sensitive: StrictBool | None = None
    enabled: StrictBool | None = None

    @model_validator(mode="after")
    def require_update(self) -> "UpdateUserRuleRequest":
        if (
            self.label is None
            and self.kind is None
            and self.effect is None
            and self.matcher is None
            and self.case_sensitive is None
            and self.enabled is None
        ):
            raise ValueError("at least one user-rule field must be updated")
        return self


class UserRuleResponse(BaseModel):
    """Safe projection of a stored user rule; matcher material is excluded."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=128)
    kind: UserRuleKind
    effect: UserRuleEffect
    case_sensitive: bool
    replacement: str = Field(min_length=1)
    revision: int = Field(ge=1)
    enabled: bool
    deleted: bool
    created_at: datetime
    updated_at: datetime


class UserRuleErrorDetail(BaseModel):
    """Stable, non-sensitive API error payload."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^user_rule\.[a-z0-9_.-]+$")


class UserRuleErrorResponse(BaseModel):
    """FastAPI-compatible error envelope."""

    model_config = ConfigDict(extra="forbid")

    detail: UserRuleErrorDetail
