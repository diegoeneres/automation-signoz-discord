from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "firing"
    labels: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None


class SignozWebhook(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "firing"
    receiver: Optional[str] = None
    alerts: list[Alert] = Field(default_factory=list)
    commonLabels: dict[str, Any] = Field(default_factory=dict)
    commonAnnotations: dict[str, Any] = Field(default_factory=dict)
    externalURL: Optional[str] = None
    groupKey: Optional[str] = None
