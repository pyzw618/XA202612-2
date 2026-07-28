import json
import os
import sys

# -------------------------------------------------------------------------
# 1. 自动定位项目根目录
# -------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from memoryhub.adapter.schemas import MemoryEvent
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.preference.llm_client import OpenAIClientAdapter

# -------------------------------------------------------------------------
# 2. 丰富后的 8 条测试集数据（适配 Pydantic 64位 SHA-256 Hash 校验）
# -------------------------------------------------------------------------
RAW_TEST_DATA = """
{"event_id": "lme:test:001", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_01", "scene": "coding_assistant", "task_type": "formatting", "occurred_at": "2026-07-28T10:00:00Z", "text": "From now on, always use markdown to respond to my code architecture queries.", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "3e3cb8653158cc19873f60644484bc3e33b5b2706d6bcaeee29a18a3aa4c3101", "redactions": [], "quality": {"score": 0.95, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
{"event_id": "lme:test:002", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_01", "scene": "data_analysis", "task_type": "privacy_control", "occurred_at": "2026-07-28T10:05:00Z", "text": "请注意保密，禁止保存我的 API 密钥和个人 token 凭证。", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "8b0f150f4ea4ead9c7cdedbadfdb9f206b91c43e3fa622c3a2b748b44080a71f", "redactions": [], "quality": {"score": 0.98, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
{"event_id": "lme:test:003", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_02", "scene": "coding_assistant", "task_type": "code_refactoring", "occurred_at": "2026-07-28T10:10:00Z", "text": "I really dislike long-winded explanations. Whenever I ask for code, just give me the minimal working code block first, and keep the explanations brief.", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "04404dd9df5fde5e83bf03c9c8ec0e23f99a459a6662b4e7b7a3f460ec384905", "redactions": [], "quality": {"score": 0.90, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
{"event_id": "lme:test:004", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_02", "scene": "learning", "task_type": "explanation", "occurred_at": "2026-07-28T10:15:00Z", "text": "In all scenarios across our chats, explain complex CS concepts using step-by-step real-world analogies rather than dry academic definitions.", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "268afea4d4f9872dce8694405318e8603036a4ddef291421a004fc1bc2b66681", "redactions": [], "quality": {"score": 0.88, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
{"event_id": "lme:test:005", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_03", "scene": "coding_assistant", "task_type": "debugging", "occurred_at": "2026-07-28T10:20:00Z", "text": "When helping me debug, I prefer you to first point out the root cause line number before proposing patches.", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "68cabe9fd23445bcaff7b9dd72c959c14174bf8da5040618d585d29aec67a31b", "redactions": [], "quality": {"score": 0.45, "status": "rejected", "completeness": 0.5, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": ["low_quality_input"]}}
{"event_id": "lme:test:006", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_03", "scene": "coding_assistant", "task_type": "algorithm", "occurred_at": "2026-07-28T10:25:00Z", "text": "以后在所有场景下，一律用 json 格式输出我的算法时空复杂度分析报告。", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0", "redactions": [], "quality": {"score": 0.96, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
{"event_id": "lme:test:007", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_04", "scene": "daily_life", "task_type": "chat", "occurred_at": "2026-07-28T10:30:00Z", "text": "I had a sandwich for lunch today and it was pretty decent.", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "f0e9d8c7b6a594837261054321fedcba0987654321fedcba0987654321fedcba", "redactions": [], "quality": {"score": 0.85, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
{"event_id": "lme:test:008", "source_type": "user_behavior", "event_type": "user_action", "user_id": "user_1001", "session_id": "sess_04", "scene": "algorithm_design", "task_type": "optimization", "occurred_at": "2026-07-28T10:35:00Z", "text": "When designing network algorithms, always prioritize lower latency and packet throughput over memory saving.", "payload": {"action": "message", "role": "user"}, "schema_version": "1.0", "source_hash": "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff", "redactions": [], "quality": {"score": 0.92, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}}
""".strip()


def run_full_pipeline_tests():
    print("🚀 初始化 LLM 客户端并开始完整偏好提取流水线测试...\n")

    # 配置 OpenAI 适配器（请确保配置了有效 api_key、base_url 和支持的模型名）
    MY_API_KEY = "sk-xen2GeBn0BleDqJOYTqiGWdbfGtTJClr024pV3Lbs3da1jnx"
    MY_BASE_URL = "https://cortexlane.cloud/v1"
    MY_MODEL = "gpt-5.6-sol"  # 可替换为其他支持的模型名称

    llm_client = OpenAIClientAdapter(
        api_key=MY_API_KEY, base_url=MY_BASE_URL, model_name=MY_MODEL
    )
    extractor = PreferenceExtractor(llm_client=llm_client)

    lines = RAW_TEST_DATA.strip().split("\n")
    print(f"📊 成功加载 {len(lines)} 条测试集事件，开始按顺序测试...\n")

    rule_extracted_count = 0
    llm_extracted_count = 0
    skipped_low_quality = 0
    no_pref_count = 0

    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue

        data = json.loads(line)
        event = MemoryEvent(**data)

        print(
            f"------------------- [事件 {idx}/{len(lines)}] -------------------"
        )
        print(f"📌 事件 ID: {event.event_id}")
        print(f"💬 用户输入: \"{event.text}\"")
        print(f"⭐ 质量评分 (quality.score): {event.quality.score}")

        # 跟踪阶段分支
        rule_candidates = extractor._rule_extract(event)
        if rule_candidates:
            print("  🔍 提取路径: [阶段 1: 规则引擎直接命中 ✅]")
            extracted_preferences = extractor.extract(event)
            rule_extracted_count += len(extracted_preferences)
        elif event.quality.score < 0.6:
            print("  ⚠️ 提取路径: [阶段 1 未命中规则 -> 阶段 2 拦截 🛑 (评分 < 0.6)]")
            extracted_preferences = extractor.extract(event)
            skipped_low_quality += 1
        else:
            print(
                "  🤖 提取路径: [阶段 1 未命中规则 -> 阶段 2 触发 LLM 隐式抽取 ✨ (评分 >= 0.6)]"
            )
            extracted_preferences = extractor.extract(event)
            if extracted_preferences:
                llm_extracted_count += len(extracted_preferences)
            else:
                no_pref_count += 1

        if extracted_preferences:
            for p_idx, pref in enumerate(extracted_preferences, 1):
                print(f"  ✅ 偏好结果 [{p_idx}]:")
                print(f"     • 描述: {pref.text}")
                print(f"     • 类型: {pref.preference_type.value}")
                print(f"     • 抽取来源: {pref.extract_source}")
                print(f"     • 全局标志: {pref.is_global}")
                print(
                    f"     • 作用域: scene={pref.scope.scene}, task_type={pref.scope.task_type}"
                )
                print(f"     • 标签: {pref.tags}")
                print(f"     • Payload: {pref.payload}")
                print(
                    f"     • 证据链数量: {len(pref.evidences)} 条 (EventID: {pref.evidences[0].event_id})"
                )
        else:
            print("  ℹ️ 最终结果: 未生成持久化偏好对象")
        print()

    print("==================================================")
    print("🎉 偏好提取流水线测试完成！统计汇总如下：")
    print(f"  • 总处理事件数: {len(lines)}")
    print(f"  • 规则命中提取: {rule_extracted_count} 条")
    print(f"  • LLM 隐式抽取: {llm_extracted_count} 条")
    print(f"  • 低质量评分拦截: {skipped_low_quality} 条")
    print(f"  • 无偏好陈述过滤: {no_pref_count} 条")
    print("==================================================")


if __name__ == "__main__":
    run_full_pipeline_tests()