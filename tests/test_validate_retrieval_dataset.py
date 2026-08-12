# -*- coding: utf-8 -*-
"""校验脚本 regression 测试。

覆盖:
  - 完全合法的样本通过校验
  - 各种典型错误被检测：重复ID、缺失引用、无效枚举、敏感词、
    必填字段缺失、status 规则、knowledge_type 规则
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.validate_retrieval_dataset import validate_dataset


# ── 辅助: 构造最小合法数据集 ───────────────────────────────────
def _valid_memory(overrides: dict | None = None) -> dict:
    m = {
        "id": "know_test_001",
        "user_id": "user_001",
        "memory_type": "knowledge",
        "knowledge_type": "workflow",
        "name": "测试工作流",
        "content": "用于测试的工作流内容描述",
        "steps": ["步骤一", "步骤二"],
        "tools": ["tool_a", "tool_b"],
        "template_body": "",
        "scope": {"scene": "office", "task_type": "office.test", "app": "agent"},
        "project_id": "project_a",
        "status": "active",
        "version": 1,
    }
    if overrides:
        m.update(overrides)
    return m


def _valid_query(overrides: dict | None = None) -> dict:
    q = {
        "query_id": "q_test_001",
        "user_id": "user_001",
        "query_text": "这是一个测试查询",
        "context": {"scene": "office", "task_type": "office.test", "app": "agent"},
        "project_id": "project_a",
        "memory_types": ["knowledge"],
        "top_k": 5,
        "difficulty": "exact",
        "language": "zh-CN",
        "relevance": {"know_test_001": 3},
        "notes": "",
    }
    if overrides:
        q.update(overrides)
    return q


def _valid_dataset(overrides: dict | None = None) -> dict:
    d = {
        "metadata": {
            "dataset_id": "memoryhub-knowledge-retrieval-v1",
            "version": "1.0.0",
            "split": "dev",
        },
        "memories": [
            _valid_memory({"id": "know_test_001"}),
            _valid_memory({
                "id": "know_test_002",
                "knowledge_type": "case",
                "steps": ["调查问题", "解决问题"],
                "name": "测试案例",
            }),
            _valid_memory({
                "id": "know_test_003",
                "knowledge_type": "template",
                "steps": ["填写模板"],
                "template_body": "# 测试模板\n{变量}",
                "name": "测试模板",
            }),
        ],
        "queries": [
            _valid_query({
                "query_id": "q_test_001",
                "relevance": {"know_test_001": 3, "know_test_002": 1},
            }),
        ],
    }
    if overrides:
        d.update(overrides)
    return d


# ════════════════════════════════════════════════════════════════
# 1. 合法样本通过校验
# ════════════════════════════════════════════════════════════════
class TestValidDatasetPasses:
    def test_minimal_valid_dataset_passes_all_checks(self) -> None:
        result = validate_dataset(_valid_dataset())
        assert result["passed"] is True
        assert len(result["errors"]) == 0
        assert result["stats"]["memory_count"] == 3
        assert result["stats"]["query_count"] == 1
        assert result["stats"]["passed"] is True

    def test_valid_template_memory_passes(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["relevance"] = {"know_test_003": 3}
        result = validate_dataset(ds)
        assert result["passed"] is True

    def test_valid_case_with_1_step_passes(self) -> None:
        m = _valid_memory({
            "id": "know_test_cs",
            "knowledge_type": "case",
            "steps": ["单个步骤"],
            "name": "单步案例",
        })
        ds = _valid_dataset()
        ds["memories"] = [m]
        ds["queries"][0]["relevance"] = {"know_test_cs": 3}
        result = validate_dataset(ds)
        assert result["passed"] is True


# ════════════════════════════════════════════════════════════════
# 2. 重复 ID
# ════════════════════════════════════════════════════════════════
class TestDuplicateId:
    def test_duplicate_memory_id_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"].append(_valid_memory({"id": "know_test_001"}))
        result = validate_dataset(ds)
        assert result["passed"] is False
        assert any("重复" in e["message"] and "know_test_001" in e["message"]
                   for e in result["errors"])

    def test_duplicate_query_id_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"].append(_valid_query({"query_id": "q_test_001"}))
        result = validate_dataset(ds)
        assert result["passed"] is False
        assert any("重复" in e["message"] for e in result["errors"])


# ════════════════════════════════════════════════════════════════
# 3. 缺失引用
# ════════════════════════════════════════════════════════════════
class TestMissingReference:
    def test_query_references_nonexistent_memory(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["relevance"] = {"know_nonexistent": 3}
        result = validate_dataset(ds)
        assert result["passed"] is False
        assert any("know_nonexistent" in e["message"] and "不存在" in e["message"]
                   for e in result["errors"])


# ════════════════════════════════════════════════════════════════
# 4. 无效枚举值
# ════════════════════════════════════════════════════════════════
class TestInvalidEnum:
    def test_invalid_knowledge_type_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["knowledge_type"] = "invalid_type"
        result = validate_dataset(ds)
        assert any("knowledge_type" in e["message"] and "invalid_type" in e["message"]
                   for e in result["errors"])

    def test_invalid_difficulty_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["difficulty"] = "very_hard"
        result = validate_dataset(ds)
        assert any("difficulty" in e["message"] for e in result["errors"])

    def test_invalid_language_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["language"] = "fr-FR"
        result = validate_dataset(ds)
        assert any("language" in e["message"] for e in result["errors"])

    def test_invalid_status_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["status"] = "pending"
        result = validate_dataset(ds)
        assert any("status" in e["message"] and "pending" in e["message"]
                   for e in result["errors"])

    def test_invalid_scope_scene_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["scope"]["scene"] = "gaming"
        result = validate_dataset(ds)
        assert any("scope.scene" in e["message"] for e in result["errors"])


# ════════════════════════════════════════════════════════════════
# 5. 必填字段缺失
# ════════════════════════════════════════════════════════════════
class TestMissingRequired:
    def test_missing_name_detected(self) -> None:
        ds = _valid_dataset()
        del ds["memories"][0]["name"]
        result = validate_dataset(ds)
        assert any("name" in e["message"] for e in result["errors"])

    def test_missing_user_id_detected(self) -> None:
        ds = _valid_dataset()
        del ds["memories"][0]["user_id"]
        result = validate_dataset(ds)
        assert any("user_id" in e["message"] for e in result["errors"])

    def test_missing_query_text_detected(self) -> None:
        ds = _valid_dataset()
        del ds["queries"][0]["query_text"]
        result = validate_dataset(ds)
        assert any("query_text" in e["message"] for e in result["errors"])

    def test_missing_context_scene_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["context"] = {"task_type": "x", "app": "x"}
        result = validate_dataset(ds)
        assert any("context.scene" in e["message"] for e in result["errors"])


# ════════════════════════════════════════════════════════════════
# 6. 敏感信息扫描
# ════════════════════════════════════════════════════════════════
class TestSensitiveContent:
    def test_api_key_in_content_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["content"] = "使用 api_key=sk-1234567890abcdef 访问"
        result = validate_dataset(ds)
        assert any("敏感信息" in e["message"] or "API Key" in e["message"]
                   for e in result["errors"])

    def test_api_key_in_query_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["query_text"] = "配置 apikey: abcdef1234567890 到环境变量"
        result = validate_dataset(ds)
        assert any("敏感" in e["message"] for e in result["errors"])

    def test_private_key_header_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["content"] = (
            "使用私钥：-----BEGIN RSA PRIVATE KEY-----\nMIIEp...\n-----END RSA PRIVATE KEY----- "
        )
        result = validate_dataset(ds)
        assert any("Private Key" in e["message"] for e in result["errors"])

    def test_password_in_steps_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["steps"] = ["设置 password: admin123456"]
        result = validate_dataset(ds)
        assert any("Password" in e["message"] for e in result["errors"])

    def test_clean_content_no_sensitive_flags(self) -> None:
        ds = _valid_dataset()
        result = validate_dataset(ds)
        assert not any("敏感" in e["message"] for e in result["errors"])


# ════════════════════════════════════════════════════════════════
# 7. Status 规则
# ════════════════════════════════════════════════════════════════
class TestStatusRules:
    def test_archived_marked_relevant_detected(self) -> None:
        m = _valid_memory({
            "id": "know_test_arch",
            "knowledge_type": "case",
            "steps": ["步骤一"],
            "status": "archived",
            "name": "已归档案例",
        })
        ds = _valid_dataset()
        ds["memories"].append(m)
        ds["queries"][0]["relevance"] = {"know_test_arch": 3}
        result = validate_dataset(ds)
        assert any("archived" in e["message"] and "不应" in e["message"]
                   for e in result["errors"])

    def test_deleted_marked_relevant_detected(self) -> None:
        m = _valid_memory({
            "id": "know_test_del",
            "knowledge_type": "case",
            "steps": ["步骤一"],
            "status": "deleted",
            "name": "已删除案例",
        })
        ds = _valid_dataset()
        ds["memories"].append(m)
        ds["queries"][0]["relevance"] = {"know_test_del": 2}
        result = validate_dataset(ds)
        assert any("deleted" in e["message"] for e in result["errors"])

    def test_replaced_missing_replaced_by_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["status"] = "replaced"
        result = validate_dataset(ds)
        assert any("replaced_by" in e["message"] for e in result["errors"])

    def test_replaced_with_valid_replaced_by_passes(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["status"] = "replaced"
        ds["memories"][0]["replaced_by"] = "know_test_002"
        result = validate_dataset(ds)
        replaced_errors = [e for e in result["errors"]
                           if "replaced_by" in e["message"] and "缺少" in e["message"]]
        assert len(replaced_errors) == 0


# ════════════════════════════════════════════════════════════════
# 8. knowledge_type 规则
# ════════════════════════════════════════════════════════════════
class TestKnowledgeTypeRules:
    def test_workflow_with_1_step_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["steps"] = ["仅一步"]
        result = validate_dataset(ds)
        assert any("workflow" in e["message"] and "steps" in e["message"]
                   for e in result["errors"])

    def test_workflow_with_2_steps_passes(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["steps"] = ["步骤一", "步骤二"]
        result = validate_dataset(ds)
        assert all("steps" not in e["message"] for e in result["errors"])

    def test_template_missing_template_body_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][2]["template_body"] = ""
        result = validate_dataset(ds)
        assert any("template_body" in e["message"] for e in result["errors"])

    def test_template_with_body_passes(self) -> None:
        ds = _valid_dataset()
        result = validate_dataset(ds)
        tmpl_errors = [e for e in result["errors"]
                       if "template_body" in e["message"]]
        assert len(tmpl_errors) == 0


# ════════════════════════════════════════════════════════════════
# 9. Relevance 规则
# ════════════════════════════════════════════════════════════════
class TestRelevanceRules:
    def test_no_answer_query_with_relevance_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["difficulty"] = "no-answer"
        result = validate_dataset(ds)
        assert any("no-answer" in e["message"] and "不应" in e["message"]
                   for e in result["errors"])

    def test_relevance_out_of_range_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["relevance"] = {"know_test_001": 5, "know_test_002": -1}
        result = validate_dataset(ds)
        assert any("不合法" in e["message"] and "5" in e["message"]
                   for e in result["errors"])

    def test_empty_relevance_for_non_noanswer_warns(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["difficulty"] = "semantic"
        ds["queries"][0]["relevance"] = {}
        result = validate_dataset(ds)
        assert any("无任何" in w["message"] or "relevance" in w["message"]
                   for w in result["warnings"])


# ════════════════════════════════════════════════════════════════
# 10. 统计完整性
# ════════════════════════════════════════════════════════════════
class TestStatsCompleteness:
    def test_stats_reflect_dataset_content(self) -> None:
        ds = _valid_dataset()
        ds["memories"].append(_valid_memory({
            "id": "know_test_004",
            "knowledge_type": "case",
            "steps": ["调查"],
            "status": "archived",
            "name": "额外案例",
        }))
        ds["queries"].append(_valid_query({
            "query_id": "q_test_002",
            "difficulty": "semantic",
            "relevance": {"know_test_001": 2},
        }))
        result = validate_dataset(ds)
        assert result["stats"]["memory_count"] == 4
        assert result["stats"]["query_count"] == 2
        assert result["stats"]["status_distribution"]["archived"] == 1

    def test_report_json_serializable(self) -> None:
        result = validate_dataset(_valid_dataset())
        json_str = json.dumps(result, ensure_ascii=False, default=str)
        parsed = json.loads(json_str)
        assert "passed" in parsed
        assert "errors" in parsed
        assert "stats" in parsed


# ════════════════════════════════════════════════════════════════
# 11. confidence / version 范围
# ════════════════════════════════════════════════════════════════
class TestValueRanges:
    def test_confidence_out_of_range_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["confidence"] = 1.5
        result = validate_dataset(ds)
        assert any("confidence" in e["message"] and "1.5" in e["message"]
                   for e in result["errors"])

    def test_version_below_one_detected(self) -> None:
        ds = _valid_dataset()
        ds["memories"][0]["version"] = 0
        result = validate_dataset(ds)
        assert any("version" in e["message"] for e in result["errors"])

    def test_top_k_out_of_range_detected(self) -> None:
        ds = _valid_dataset()
        ds["queries"][0]["top_k"] = 100
        result = validate_dataset(ds)
        assert any("top_k" in e["message"] for e in result["errors"])
