"""ConfigAdapter：把手动配置适配为版本化 ManualConfig + MANUAL_CONFIG MemoryEvent。

手动配置（输出风格 / 安全策略 / 通用）是偏好的强来源（source 因子 0.95），且
赛题点名"配置版本混乱"——本适配器每次修改生成新版本（config_id 不变，
version/parent_id/root_id 构成版本链），同时打成一个 ``MANUAL_CONFIG`` 事件进入
统一接收链（REFACTOR_PLAN_V2 §4.1.1 / I-7）。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from memoryhub.adapter.schemas import (
    EventQuality,
    ManualConfig,
    MemoryEvent,
    QualityStatus,
    SceneScope,
    SourceType,
)


class ConfigAdapter:
    """手动配置源适配器：配置修改 → 版本化 ManualConfig + MemoryEvent。"""

    VALID_CONFIG_TYPES = {"output_style", "safety_policy", "general"}

    def __init__(self, version: int | None = None) -> None:
        self._next_version = int(version or 1)

    def _bump_version(self) -> int:
        version = self._next_version
        self._next_version += 1
        return version

    def to_manual_config(
        self,
        *,
        user_id: str,
        config_type: str,
        payload: dict[str, Any],
        previous: ManualConfig | None = None,
        scope: SceneScope | None = None,
        config_id: str = "",
    ) -> ManualConfig:
        """把一次配置修改解析为带版本链的 ManualConfig。

        Args:
            user_id: 归属用户。
            config_type: 配置类型（output_style/safety_policy/general）。
            payload: 配置内容（任意 JSON 对象）。
            previous: 同 config 的上一个版本（用于构建版本链），可为 None。
            scope: 生效作用域，缺省取 previous.scope。
            config_id: 固定配置 ID；缺省时首次生成，后续沿用 previous.config_id。

        Returns:
            版本化 ManualConfig。

        Raises:
            ValueError: 配置类型非法、payload 非 dict 或为空。
        """
        if config_type not in self.VALID_CONFIG_TYPES:
            raise ValueError(f"invalid config_type: {config_type!r}")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("config payload must be a non-empty object")

        cid = (
            config_id
            or (previous.config_id if previous else "")
            or f"config_{uuid.uuid4().hex[:16]}"
        )
        parent_id = previous.config_id if previous else ""
        root_id = (previous.root_id or previous.config_id) if previous else cid
        version = (previous.version + 1) if previous else self._bump_version()
        effective_scope = scope or (previous.scope if previous else SceneScope())

        return ManualConfig(
            config_id=cid,
            user_id=user_id,
            config_type=config_type,
            payload=payload,
            version=version,
            parent_id=parent_id,
            root_id=root_id,
            scope=effective_scope,
            source="manual_config",
            created_at=_utc_now(),
        )

    def to_event(
        self,
        config: ManualConfig,
        *,
        previous: ManualConfig | None = None,
    ) -> MemoryEvent:
        """把版本化 ManualConfig 打成一个 MANUAL_CONFIG MemoryEvent。"""
        stable_material = {
            "config_id": config.config_id,
            "user_id": config.user_id,
            "config_type": config.config_type,
            "version": config.version,
            "payload": config.payload,
            "scene": config.scope.scene,
            "task_type": config.scope.task_type,
            "app": config.scope.app,
        }
        source_hash = hashlib.sha256(
            json.dumps(
                stable_material, ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")
        ).hexdigest()
        text = json.dumps(config.payload, ensure_ascii=False, default=str)

        raw = {
            "event_id": f"config_{config.config_id}_{config.version}",
            "source_type": SourceType.MANUAL_CONFIG,
            "event_type": "manual_config",
            "user_id": config.user_id,
            "session_id": "",
            "turn_id": "",
            "scene": config.scope.scene,
            "task_type": config.scope.task_type,
            "occurred_at": _utc_now(),
            "text": text,
            "payload": {
                "config_id": config.config_id,
                "config_type": config.config_type,
                "version": config.version,
                "parent_id": config.parent_id,
                "root_id": config.root_id,
                "payload": config.payload,
                **({"previous_version": previous.version} if previous else {}),
            },
            "schema_version": "1.1",
            "source_hash": source_hash,
            "redactions": [],
            "quality": {
                "score": 1.0,
                "status": QualityStatus.ACCEPTED.value,
                "completeness": 1.0,
                "validity": 1.0,
                "consistency": 1.0,
                "freshness": 1.0,
                "issues": [],
            },
        }
        return MemoryEvent.model_validate(raw)

    @staticmethod
    def from_event(event: MemoryEvent) -> ManualConfig | None:
        """从 MANUAL_CONFIG 事件反解析 ManualConfig（供读取/回滚定位）。"""
        payload = dict(event.payload or {})
        cfg_payload = payload.get("payload")
        if not isinstance(cfg_payload, dict):
            return None
        return ManualConfig(
            config_id=str(payload.get("config_id") or ""),
            user_id=event.user_id,
            config_type=str(payload.get("config_type") or ""),
            payload=cfg_payload,
            version=int(payload.get("version") or 1),
            parent_id=str(payload.get("parent_id") or ""),
            root_id=str(payload.get("root_id") or ""),
            scope=SceneScope(
                scene=event.scene or "",
                task_type=event.task_type or "",
                app="",
            ),
            source="manual_config",
            created_at=event.occurred_at or "",
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
