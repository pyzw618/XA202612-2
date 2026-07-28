import os
import sys

# -------------------------------------------------------------------------
# 自动寻找并添加根目录到 sys.path
# 当前文件在: memoryhub/core/preference/test_preference_extractor.py
# 向上退三层目录即可定位到项目根目录 (包含 memoryhub 文件夹的那个目录)
# -------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../../../"))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -------------------------------------------------------------------------
# 接下来再进行项目的模块导入，就不会报错了
# -------------------------------------------------------------------------
from memoryhub.core.preference.llm_client import OpenAIClientAdapter
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.adapter.schemas import (
    MemoryEvent,
    SourceType,
    EventQuality,
    MemoryLevel,
    PreferenceType,
    QualityStatus,
)

def run_tests():
    # 1. 初始化 API 客户端
    print("正在初始化 Windows 环境 API 客户端...")
    
    # ⚠️ 请将 model_name 修改为你当前使用的模型名称
    llm_client = OpenAIClientAdapter(model_name="gpt-5.6-sol")

    # 2. 实例化偏好抽取器
    extractor = PreferenceExtractor(llm_client=llm_client)
    print("✅ 偏好抽取器初始化完成！\n")

    # =========================================================================
    # 测试场景 1：规则 A 测试（格式偏好 / 局部作用域）
    # =========================================================================
    print("--- [测试 1/3] 规则 A 匹配（格式偏好）---")
    # 创建一个通用的高质量 EventQuality 测试对象
    default_quality = EventQuality(
    score=0.9,
    status=QualityStatus.VALID,  # 或者如果 QualityStatus 是 StrEnum，也可以用 "valid"
    completeness=0.9,
    validity=0.9,
    consistency=0.9,
    freshness=0.9,
    issues=[],  # 有默认值，可传可不传
    )
    event_rule_a = MemoryEvent(
        user_id="user_win_001",
        source_type=SourceType.USER_BEHAVIOR,
        text="以后写 Python 代码时，默认用 json 格式返回数据",
        scene="coding",
        task_type="python",
        quality=default_quality,
    )
    res_a = extractor.extract(event_rule_a)
    _print_results("规则 A", res_a)

    # =========================================================================
    # 测试场景 2：规则 B 测试（隐私与安全约束 / 全局域）
    # =========================================================================
    print("\n--- [测试 2/3] 规则 B 匹配（隐私安全约束）---")
    event_rule_b = MemoryEvent(
        user_id="user_win_001",
        source_type=SourceType.USER_BEHAVIOR,
        text="Please don't save my passwords, tokens, or live location anywhere.",
        scene="chat",
        quality=default_quality,
    )
    res_b = extractor.extract(event_rule_b)
    _print_results("规则 B", res_b)

    # =========================================================================
    # 测试场景 3：LLM 辅助抽取（调用在线 API / 隐式偏好 + 双重 global 验证）
    # =========================================================================
    print("\n--- [测试 3/3] LLM 辅助抽取（触发真实 API 调用中...）---")
    event_llm = MemoryEvent(
        user_id="user_win_001",
        source_type=SourceType.USER_BEHAVIOR,
        text="In all scenarios, please keep your technical code explanations super concise and brief.",
        scene="coding",
        task_type="code_review",
        payload={
            "status": "SUCCESS",
            "date": "2026-07-28",  # 会被 clean_payload 自动过滤
            "user_rating": 5
        },
        quality=EventQuality(score=0.85),  # 分数 >= 0.6 触发 LLM 抽取
    )
    res_llm = extractor.extract(event_llm)
    _print_results("LLM 抽取", res_llm)


def _print_results(test_name: str, results: list):
    if not results:
        print(f"⚠️ {test_name}: 未匹配到任何偏好！")
        return

    for idx, pref in enumerate(results, 1):
        print(f"✅ {test_name} [{idx}] 抽取成功：")
        print(f"  • 偏好描述 (text):       {pref.text}")
        print(f"  • 偏好类型 (type):       {pref.preference_type}")
        print(f"  • 是否全局 (is_global):  {pref.is_global}")
        print(f"  • 作用域 (scope):        scene='{pref.scope.scene}', task_type='{pref.scope.task_type}'")
        print(f"  • 记忆层级 (level):      {pref.level}")
        print(f"  • 抽取来源 (source):     {pref.extract_source}")
        print(f"  • 标签 (tags):           {pref.tags}")


if __name__ == "__main__":
    run_tests()