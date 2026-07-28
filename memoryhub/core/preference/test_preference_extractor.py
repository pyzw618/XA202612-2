import json
import os
import sys

# -------------------------------------------------------------------------
# 1. 自动定位根目录
# -------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from memoryhub.adapter.schemas import MemoryEvent
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.preference.llm_client import OpenAIClientAdapter

# 数据清洗团队提供的测试集原始 JSON 文本
RAW_TEST_DATA = """
{"event_id": "lme:gpt4_2655b836:answer_4be1b6b4_2:0", "source_type": "user_behavior", "event_type": "user_action", "user_id": "longmemeval:gpt4_2655b836", "session_id": "answer_4be1b6b4_2", "scene": "long_term_memory", "task_type": "temporal-reasoning", "occurred_at": "2023-04-10T17:50:00Z", "text": "I'm thinking of getting my car detailed soon. Do you know any good detailers in the area or have any recommendations? By the way, I just got my car serviced for the first time on March 15th, and it was a great experience.", "payload": {"action": "message", "role": "user", "has_answer": true}, "schema_version": "1.0", "source_hash": "3e3cb8653158cc19873f60644484bc3e33b5b2706d6bcaeee29a18a3aa4c3101", "redactions": [], "quality": {"score": 0.94, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 0.4, "issues": ["freshness:stale_event"]}}
{"event_id": "lme:gpt4_2655b836:answer_4be1b6b4_2:2", "source_type": "user_behavior", "event_type": "user_action", "user_id": "longmemeval:gpt4_2655b836", "session_id": "answer_4be1b6b4_2", "scene": "long_term_memory", "task_type": "temporal-reasoning", "occurred_at": "2023-04-10T17:50:00Z", "text": "I'll definitely check out those review websites and ask around for referrals. Do you think it's a good idea to get a wax and detailing done every 3-4 months to maintain the car's appearance and protect the paint?", "payload": {"action": "message", "role": "user", "has_answer": false}, "schema_version": "1.0", "source_hash": "8b0f150f4ea4ead9c7cdedbadfdb9f206b91c43e3fa622c3a2b748b44080a71f", "redactions": [], "quality": {"score": 0.94, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 0.4, "issues": ["freshness:stale_event"]}}
{"event_id": "lme:gpt4_2655b836:answer_4be1b6b4_2:4", "source_type": "user_behavior", "event_type": "user_action", "user_id": "longmemeval:gpt4_2655b836", "session_id": "answer_4be1b6b4_2", "scene": "long_term_memory", "task_type": "temporal-reasoning", "occurred_at": "2023-04-10T17:50:00Z", "text": "Yup, that makes sense. I've been keeping track of my gas mileage too, and I've been getting around 32 miles per gallon, which is better than my old car.", "payload": {"action": "message", "role": "user", "has_answer": false}, "schema_version": "1.0", "source_hash": "04404dd9df5fde5e83bf03c9c8ec0e23f99a459a6662b4e7b7a3f460ec384905", "redactions": [], "quality": {"score": 0.94, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 0.4, "issues": ["freshness:stale_event"]}}
{"event_id": "lme:gpt4_2655b836:answer_4be1b6b4_2:6", "source_type": "user_behavior", "event_type": "user_action", "user_id": "longmemeval:gpt4_2655b836", "session_id": "answer_4be1b6b4_2", "scene": "long_term_memory", "task_type": "temporal-reasoning", "occurred_at": "2023-04-10T17:50:00Z", "text": "I've also been using the rewards program at the Shell gas station near my office to earn points. Do you think it's worth it to focus on earning points at one gas station or to try to earn points across multiple stations?", "payload": {"action": "message", "role": "user", "has_answer": false}, "schema_version": "1.0", "source_hash": "268afea4d4f9872dce8694405318e8603036a4ddef291421a004fc1bc2b66681", "redactions": [], "quality": {"score": 0.94, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 0.4, "issues": ["freshness:stale_event"]}}
{"event_id": "lme:gpt4_2655b836:answer_4be1b6b4_2:8", "source_type": "user_behavior", "event_type": "user_action", "user_id": "longmemeval:gpt4_2655b836", "session_id": "answer_4be1b6b4_2", "scene": "long_term_memory", "task_type": "temporal-reasoning", "occurred_at": "2023-04-10T17:50:00Z", "text": "I've also been redeeming points from my credit card to get rewards. I recently redeemed 50,000 points to get a $500 gift card to a car accessories store. I used it to purchase a new car cover, floor mats, and a steering wheel cover, which I'm really happy with.", "payload": {"action": "message", "role": "user", "has_answer": false}, "schema_version": "1.0", "source_hash": "68cabe9fd23445bcaff7b9dd72c959c14174bf8da5040618d585d29aec67a31b", "redactions": [], "quality": {"score": 0.94, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 0.4, "issues": ["freshness:stale_event"]}}
""".strip()


def run_dataset_tests():
    print("🚀 正在加载 API 客户端并分析清洗后的测试集...\n")
    llm_client = OpenAIClientAdapter(model_name="gpt-5.6-sol")
    extractor = PreferenceExtractor(llm_client=llm_client)

    # 逐行解析 JSONL 测试集数据
    lines = RAW_TEST_DATA.strip().split("\n")
    print(f"📊 成功读取 {len(lines)} 条用户行为事件，开始提取隐式偏好...\n")

    total_extracted = 0

    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue

        data = json.loads(line)

        # 反序列化为标准的 MemoryEvent（验证字段匹配度）
        event = MemoryEvent(**data)

        print(
            f"------------------- [事件 {idx}/{len(lines)}] -------------------"
        )
        print(f"📌 事件 ID: {event.event_id}")
        print(f"💬 用户输入: \"{event.text}\"")

        # 执行抽取
        extracted_preferences = extractor.extract(event)

        if extracted_preferences:
            total_extracted += len(extracted_preferences)
            for p_idx, pref in enumerate(extracted_preferences, 1):
                print(f"  ✅ 提取到偏好 [{p_idx}]:")
                print(f"     • 描述: {pref.text}")
                print(f"     • 类型: {pref.preference_type}")
                print(f"     • 全局: {pref.is_global}")
                print(f"     • 作用域: scene={pref.scope.scene}")
        else:
            print("  ℹ️ 未从该单条文本中提取出硬偏好/有效偏好")
        print()

    print(
        f"🎉 测试集测试完毕！共处理 {len(lines)} 条事件，成功抽取出 {total_extracted} 条持久化偏好对象。"
    )


if __name__ == "__main__":
    run_dataset_tests()