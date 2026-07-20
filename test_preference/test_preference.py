import sys
import os

# 将项目根目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pytest
from datetime import datetime, timezone, timedelta
from memoryhub.adapter.schemas import (
    MemoryEvent,
    EventType,
    PreferenceMemory,
    PreferenceType,
    MemoryStatus,
    SceneScope,
     Evidence,
)
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.preference.confidence import ConfidenceCalculator
from memoryhub.core.preference.updater import PreferenceUpdater


# ============================================================
# 0. Mock LLM 客户端（用于测试隐式偏好提取的 GVR 黄金循环）
# ============================================================
class MockLLMClient:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.call_count < len(self.responses):
            res = self.responses[self.call_count]
            self.call_count += 1
            return res
        return "{}"


# ============================================================
# 1. 辅助函数：构造标准偏好事件 (类比原代码的 _make_event)
# ============================================================
def _make_preference_event(
    event_type: EventType, 
    content: dict, 
    status: str = "SUCCESS", 
    user_action: str = "CONFIRM"
) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"ev_pref_{int(datetime.now(timezone.utc).timestamp())}",
        user_id="u1",
        session_id="s1",
        task_id="t1",
        event_type=event_type,
        source="os_agent",
        content=content,
        scene="office",
        task_type="office.weekly_report",
        timestamp=datetime.now(timezone.utc),
        quality_score=0.8,
        metadata={
            "status": status,       # 对应改进建议中的统一状态字段
            "user_action": user_action, # 对应改进建议中的统一动作字段
        },
    )


# ============================================================
# 2. 测试用例 1：规则与显式偏好提取 (类比知识模块的轨迹提取测试)
# ============================================================
def test_extract_from_explicit_feedback_creates_rules():
    # 模拟用户表达显式的格式硬约束
    event = _make_preference_event(
        event_type=EventType.USER_FEEDBACK,
        content={"text": "以后默认都用 markdown 格式生成周报"},
    )

    extractor = PreferenceExtractor()
    candidates = extractor.extract(event)

    assert len(candidates) >= 1
    assert candidates[0].preference_type == PreferenceType.FORMAT_PREF
    assert "MARKDOWN" in candidates[0].content


def test_extract_implicit_via_llm_gvr_retry():
    # 模拟大模型第一次吐出带有硬编码槽位的非法偏好，第二次自愈合纠正
    mock_responses = [
        '{"implicit_pref": "price_range=cheap 类型的票", "preference_type": "output_style"}', # 非法偏好（含等号和槽位）
        '{"implicit_pref": "用户表现出强烈的经济型低成本出行偏好", "preference_type": "output_style"}'  # 合法抽象偏好
    ]
    llm_client = MockLLMClient(mock_responses)
    extractor = PreferenceExtractor(llm_client=llm_client)

    # 质量评分达标 (>= 0.6) 才会触发隐式 LLM 抽取
    event = _make_preference_event(
        event_type=EventType.USER_BEHAVIOR,
        content={"clicked_button": "low_cost_flight"},
    )
    event.quality_score = 0.8

    candidates = extractor.extract(event)

    assert len(candidates) == 1
    assert llm_client.call_count == 2  # 验证 GVR 循环自愈机制成功触发并重试
    assert candidates[0].preference_type == PreferenceType.OUTPUT_STYLE
    assert "低成本" in candidates[0].content


# ============================================================
# 3. 测试用例 2：置信度与成事成效惩罚 (类比知识模块的生命周期/质量测试)
# ============================================================
def test_confidence_calculator_with_override_penalty():
    calculator = ConfidenceCalculator()
    
    # 初始化一条基础偏好
    pref = PreferenceMemory(
        user_id="u1",
        content="项目周报默认使用 Markdown",
        preference_type=PreferenceType.FORMAT_PREF,
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
    )

    # 1. 模拟一次正向确认事件，更新置信度
    event_ok = _make_preference_event(EventType.USER_BEHAVIOR, {}, status="SUCCESS", user_action="CONFIRM")
    conf_ok = calculator.update_confidence(pref, event_ok)
    
    # 2. 模拟发生了严重的言语行为成事偏差（用户被迫对系统结果进行 OVERRIDE 覆写）
    event_err = _make_preference_event(EventType.TOOL_CALL, {}, status="API_FAIL", user_action="OVERRIDE")
    conf_damaged = calculator.update_confidence(pref, event_err)

    # 遭受成事惩罚项（Speech Act Bias Penalty）后，置信度应当产生明显下跌或受到极性压制
    assert conf_damaged < conf_ok or any("OVERRIDE_ERROR" in e.content for e in pref.evidences)


# ============================================================
# 4. 测试用例 3：时序一致性崩溃与物理 Revert 回滚 (偏好特有的版本链测试)
# ============================================================
def test_preference_updater_time_series_collapse_and_revert():
    updater = PreferenceUpdater()
    updater._mock_db.clear()  # 隔离清理

    # 1. 提交初代安全稳定的偏好 (v1 Commit)
    v1_pref = PreferenceMemory(
        user_id="u1",
        content="偏好使用经典暗黑代码主题",
        preference_type=PreferenceType.OUTPUT_STYLE,
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
    )
    # 给 v1 注入 7 天内的健康交互证据
    v1_pref.evidences.append(
        Evidence(content="Status:SUCCESS Action:CONFIRM", timestamp=datetime.now(timezone.utc) - timedelta(days=1))
    )
    v1_id = updater.add(v1_pref)

    # 2. 模拟产生冲突或受噪声干扰提取的偏好升级版 (v2 Commit)
    v2_pref = PreferenceMemory(
        user_id="u1",
        content="偏好使用高亮白色代码主题",  # 噪声/错误偏好
        preference_type=PreferenceType.OUTPUT_STYLE,
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
    )
    v2_id = updater.add(v2_pref)

    assert updater._mock_db[v2_id].version == 2
    assert updater._mock_db[v2_id].parent_id == v1_id
    assert updater._mock_db[v1_id].status == MemoryStatus.ARCHIVED

    # 3. 构造时序一致性崩溃场景：用户在最近交互中疯狂纠错，连续 3 次触发 OVERRIDE 覆写
    now = datetime.now(timezone.utc)
    updater._mock_db[v2_id].evidences.extend([
        Evidence(content="Status:SUCCESS Action:OVERRIDE", timestamp=now - timedelta(hours=3)),
        Evidence(content="Status:SUCCESS Action:OVERRIDE", timestamp=now - timedelta(hours=2)),
        Evidence(content="Status:SUCCESS Action:OVERRIDE", timestamp=now - timedelta(hours=1)),
    ])

    # 4. 下一次交互发生事件演化更新，触发物理 Revert 回退
    dummy_new_pref = PreferenceMemory(
        user_id="u1",
        content="偏好使用护眼绿色代码主题",
        preference_type=PreferenceType.OUTPUT_STYLE,
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
    )
    
    # 执行更新，触发回滚算法逻辑
    active_id = updater.update(v2_id, dummy_new_pref)

    # 5. 黄金断言：系统应当无视 dummy_new_pref，断开污染分支，将稳定的 v1 重新激活（ACTIVE）
    assert active_id == v1_id
    assert updater._mock_db[v1_id].status == MemoryStatus.ACTIVE
    assert updater._mock_db[v2_id].status == MemoryStatus.ARCHIVED