"""生成 v2 偏好提取数据集（标签来自规格，含当前系统会失败的样本）。

**与旧 showcase 数据集的关键差异**

``evaluation/showcase/generate_datasets.py`` 把 ``expected_output`` 直接写成
规则抽取器的固定输出字符串（"偏好使用 MARKDOWN 格式进行数据输出。"），于是
标签与实现互为镜像，指标恒为 100%。本生成器：

1. 标签描述**规格**（该说法的正确语义是"格式偏好 / output_format / MARKDOWN"），
   不是某次运行的输出文本；
2. 每个 case 标注 ``label_source``（引用的规格条款），评审可比对；
3. **包含当前系统会失败的样本**：``llm_required`` 块（规则不命中，只能靠 LLM）
   与 ``hard_negative`` 块（不该产出偏好）。只收录能过的样本等于自证。

**三个块由机械校验保证**（``rule_rule_fires``）：生成器内置规则抽取器的等价
判据，构建时断言 ``rule_hit`` 必然命中规则、``llm_required`` 必然不命中。分类
写错会在生成阶段直接失败，而不是等到评测时才暴露。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "evaluation" / "datasets"
GENERATOR_NAME = "generate_preference_v2"
SPEC_VERSION = "v2.1"
DEFAULT_CREATED_AT = "2026-09-10T00:00:00Z"
LABEL_SOURCE = f"spec:preference-extraction-{SPEC_VERSION}#blocks"

#: 与 ``memoryhub/core/preference/extractor.py`` 规则 A 等价的格式偏好判据。
_RULE_A = re.compile(
    r"(以后|默认|每次|常规|随时|始终|一律|总是|长期|全局|所有场景|任何场景|任何地方|在任何地方|跨场景"
    r"|always|default|from now on|globally|everywhere|all scenarios|all contexts)"
    r".*(用|using|use)\s*(markdown|html|json|xml|csv)",
    re.IGNORECASE,
)

#: 与规则 B 等价的隐私/硬约束关键词（保持与抽取器同步）。
_PRIVACY_KEYWORDS = (
    "不要记住", "别记录", "不要保存", "别存", "禁止记录", "禁止保存", "不准保存", "勿记", "擦除",
    "隐私", "安全", "保密", "机密", "敏感", "合规",
    "密码", "密钥", "token", "凭证", "身份证", "手机号", "信用卡", "银行卡", "地址", "轨迹", "位置",
    "don't remember", "do not record", "don't save", "never store", "privacy", "sensitive",
    "password", "secret", "api_key", "credential", "location", "token",
)

#: 全局作用域关键词（决定规则 A 是否置 is_global）。
_GLOBAL_KEYWORDS = (
    "全局", "所有场景", "任何场景", "任何地方", "在任何地方", "跨场景", "始终", "一律", "总是",
    "globally", "everywhere", "always", "all scenarios", "all contexts",
)

#: 规则 A 实际接受的格式词（注意不含 "md"，写 "md" 不会触发规则）。
RULE_FORMAT_TOKENS = ("markdown", "html", "json", "xml", "csv")

FORMAT_TO_CANONICAL = {token: token.upper() for token in RULE_FORMAT_TOKENS}

DOMAIN_SCENES = ("office", "development", "operations", "project_management", "personal", "security")


def rule_fires(text: str) -> tuple[bool, bool]:
    """返回 ``(规则A命中, 规则B命中)``，与抽取器的两条规则等价。"""
    return bool(_RULE_A.search(text or "")), any(
        keyword in (text or "").lower() for keyword in _PRIVACY_KEYWORDS
    )


def _rule_a_case(text: str, fmt: str, scene: str, case_id: str) -> dict[str, Any]:
    is_global = any(keyword in text.lower() for keyword in _GLOBAL_KEYWORDS)
    return {
        "case_id": case_id,
        "block": "rule_hit",
        "input_text": text,
        "expected_found": True,
        "expected_type_any_of": ["format_preference"],
        "expected_target": "output_format",
        "expected_value": FORMAT_TO_CANONICAL[fmt.lower()],
        "expected_global": is_global,
        "scene": scene,
        "label_source": LABEL_SOURCE,
        "spec_rationale": (
            "规格：显式格式指令（全局/默认修饰词 + 用 + 格式词）应抽为格式偏好，"
            "payload.target=output_format，value 归一化为大写格式名；"
            "含全局修饰词时 is_global=true。"
        ),
    }


def _rule_b_case(text: str, scene: str, case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "block": "rule_hit",
        "input_text": text,
        "expected_found": True,
        "expected_type_any_of": ["safety_preference"],
        "expected_target": "sensitive_data",
        "expected_value": "forbidden",
        "expected_global": True,
        "scene": scene,
        "label_source": LABEL_SOURCE,
        "spec_rationale": (
            "规格：涉及隐私/凭证的存储限制应抽为安全硬约束，"
            "payload.target=sensitive_data，value=forbidden，且作用域为全局。"
        ),
    }


def _llm_case(
    text: str,
    types: list[str],
    scene: str,
    case_id: str,
    *,
    target: str = "",
    value: str = "",
    rationale: str = "",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "block": "llm_required",
        "input_text": text,
        "expected_found": True,
        "expected_type_any_of": types,
        "expected_target": target,
        "expected_value": value,
        # None = 不作断言：LLM 是否判定为全局作用域不可预先确定，硬断言会引入噪声。
        "expected_global": None,
        "scene": scene,
        "label_source": LABEL_SOURCE,
        "spec_rationale": rationale or (
            "规格：该说法不含规则触发词，属于隐式偏好，必须由 LLM 抽取路径产出；"
            "类型须落在允许集合内。"
        ),
    }


def _negative_case(text: str, scene: str, case_id: str, rationale: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "block": "hard_negative",
        "input_text": text,
        "expected_found": False,
        "expected_type_any_of": [],
        "expected_target": "",
        "expected_value": "",
        "expected_global": False,
        "scene": scene,
        "label_source": LABEL_SOURCE,
        "spec_rationale": rationale,
    }


# ---------------------------------------------------------------- 内容构建

_FORMAT_TEMPLATES = (
    ("以后都用 {fmt} 写{doc}", "office"),
    ("默认用 {fmt} 输出接口数据", "development"),
    ("每次汇报都改用 {fmt} 格式", "project_management"),
    ("始终用 {fmt} 格式返回结果", "development"),
    ("所有场景都用 {fmt} 输出", "office"),
    ("常规情况下用 {fmt} 格式整理材料", "personal"),
    ("以后写运维周报一律用 {fmt}", "operations"),
    ("从现在起默认用 {fmt} 保存配置说明", "operations"),
    ("任何场景都用 {fmt} 格式交付", "project_management"),
    ("长期用 {fmt} 格式沉淀文档", "security"),
)

_PRIVACY_TEMPLATES = (
    "不要保存我的密码和定位信息",
    "别记录我的手机号",
    "以后不要记住我的身份证号",
    "禁止保存聊天里的银行卡信息",
    "不要保存我的登录凭证",
    "别把密钥写进持久存储",
    "不要记录我的家庭地址",
    "擦除我之前的行程轨迹",
    "不准保存客户的身份信息",
    "别存任何 token 到磁盘",
)

# (说法, 允许类型, 目标, 值, 场景, 理由)
_LLM_TEMPLATES: tuple[tuple[str, list[str], str, str, str, str], ...] = (
    # 隐式偏好的 payload target/value 命名不属于固定契约（LLM 可自由组织语义），
    # 因此 llm_required 块只硬断言 preference_type，target/value 一律留空。
    ("处理数据时我更倾向于用 Python 而不是表格软件", ["tool_preference"], "", "", "development",
     "规格：表达工具选择倾向 → tool_preference（payload 命名不作要求）。"),
    ("复杂查询我一般直接用命令行工具搞定", ["tool_preference"], "", "", "operations",
     "规格：工具选择倾向 → tool_preference（工具名不作硬性要求）。"),
    ("画流程图我习惯用 draw.io", ["tool_preference"], "", "", "project_management",
     "规格：工具选择倾向 → tool_preference。"),
    ("看日志我更愿意用命令行而不是图形界面", ["tool_preference"], "", "", "operations",
     "规格：工具选择倾向 → tool_preference。"),
    ("抓网页数据我都用脚本而不是手工复制", ["tool_preference"], "", "", "development",
     "规格：工具选择倾向 → tool_preference。"),
    ("报告开头先给结论，细节放到后面展开", ["output_style"], "", "", "office",
     "规格：输出组织方式偏好 → output_style。"),
    ("给我的说明尽量短，能一句话说清就别写三段", ["output_style"], "", "", "personal",
     "规格：篇幅与风格偏好 → output_style。"),
    ("代码示例请带上必要的注释说明", ["output_style"], "", "", "development",
     "规格：产出风格偏好 → output_style。"),
    ("回答时先说明风险再给建议", ["output_style"], "", "", "security",
     "规格：回答结构偏好 → output_style。"),
    ("表格里的数字统一保留两位小数", ["output_style"], "", "", "project_management",
     "规格：呈现细节偏好 → output_style。"),
    ("部署前先跑一遍回归测试再发布", ["workflow_preference"], "", "", "operations",
     "规格：流程习惯偏好 → workflow_preference。"),
    ("提交代码前自动格式化并跑静态检查", ["workflow_preference"], "", "", "development",
     "规格：流程习惯偏好 → workflow_preference。"),
    ("立项之前先把验收口径写清楚", ["workflow_preference"], "", "", "project_management",
     "规格：流程习惯偏好 → workflow_preference。"),
    ("处理线上问题先留存现场再动手改", ["workflow_preference"], "", "", "operations",
     "规格：处置流程偏好 → workflow_preference。"),
    ("需求确认后再排期，避免反复返工", ["workflow_preference"], "", "", "project_management",
     "规格：流程习惯偏好 → workflow_preference。"),
    ("对客户的材料统一用中文撰写", ["language_preference"], "", "", "office",
     "规格：语言偏好 → language_preference。"),
    ("技术文档保持英文，方便外部协作", ["language_preference"], "", "", "development",
     "规格：语言偏好 → language_preference。"),
    ("给日本合作方的内容尽量用日文", ["language_preference"], "", "", "office",
     "规格：语言偏好 → language_preference。"),
    ("内部沟通用中英混排也没问题，不用刻意翻译", ["language_preference"], "", "", "development",
     "规格：语言偏好 → language_preference。"),
    ("开会的时候把通知静音，别打断", ["scene_preference"], "", "", "office",
     "规格：场景相关偏好 → scene_preference。"),
    ("专注写代码时段不要推送消息", ["scene_preference"], "", "", "development",
     "规格：场景相关偏好 → scene_preference。"),
    ("演示场合尽量少用专业术语", ["scene_preference"], "", "", "office",
     "规格：场景相关偏好 → scene_preference。"),
    ("评审会上先把背景讲清楚再谈细节", ["workflow_preference", "scene_preference"], "", "", "project_management",
     "规格：会议流程偏好，允许流程或场景类型。"),
    ("关注的信息优先看结论和数字", ["output_style"], "", "", "personal",
     "规格：信息取舍偏好 → output_style。"),
    ("给我的清单按优先级排序", ["output_style"], "", "", "personal",
     "规格：组织方式偏好 → output_style。"),
)

_NEGATIVE_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("服务器 IP 是 10.0.0.5", "security", "规格：客观事实不是偏好，必须判为未抽取。"),
    ("这个项目的负责人是张工", "project_management", "规格：人员归属是事实，不是偏好。"),
    ("账单日期是每月 7 号", "personal", "规格：日期事实不是偏好。"),
    ("本周的版本号是 2.4.1", "development", "规格：版本信息是事实。"),
    ("会议室在三楼东侧", "office", "规格：地点事实不是偏好。"),
    ("这次用红色标注一下就行", "office", "规格：一次性指令不构成长期偏好。"),
    ("今天先提交一版草稿", "development", "规格：临时安排不是偏好。"),
    ("这一单先按老流程走", "operations", "规格：单次行为不构成偏好。"),
    ("怎么把周报导出成 PDF？", "office", "规格：疑问句不是偏好陈述。"),
    ("帮我查一下上周的提交记录", "development", "规格：一次性请求不是偏好。"),
    ("现在几点了", "personal", "规格：无偏好语义。"),
    ("把这段日志贴给我看看", "operations", "规格：即时操作请求。"),
    ("明天的会议记得提前十分钟到", "office", "规格：单次提醒不是偏好。"),
    ("这个方案定价是 199 元", "project_management", "规格：金额事实不是偏好。"),
    ("数据库当前的连接数是 42", "operations", "规格：运行时状态不是偏好。"),
    ("客户下周三来拜访", "office", "规格：日程事实不是偏好。"),
)


def generate(*, created_at: str = DEFAULT_CREATED_AT, seed: int = 42) -> dict[str, Any]:
    """构建 240 条偏好提取评测样本。"""
    samples: list[dict[str, Any]] = []
    counter = 0

    # ---- 规则命中块：100 条（格式偏好 70 + 隐私约束 30）
    formats = list(RULE_FORMAT_TOKENS)
    for index in range(70):
        template, scene = _FORMAT_TEMPLATES[index % len(_FORMAT_TEMPLATES)]
        fmt = formats[index % len(formats)]
        text = template.format(fmt=fmt, doc="周报")
        counter += 1
        samples.append(_rule_a_case(text, fmt, scene, f"pref2_rule_{counter:04d}"))
    for index in range(30):
        text = _PRIVACY_TEMPLATES[index % len(_PRIVACY_TEMPLATES)]
        scene = DOMAIN_SCENES[index % len(DOMAIN_SCENES)]
        counter += 1
        samples.append(_rule_b_case(text, scene, f"pref2_rule_{counter:04d}"))

    # ---- 需 LLM 块：100 条（模板循环，措辞各异）
    for index in range(100):
        text, types, target, value, scene, rationale = _LLM_TEMPLATES[index % len(_LLM_TEMPLATES)]
        counter += 1
        samples.append(
            _llm_case(text, list(types), scene, f"pref2_llm_{counter:04d}",
                      target=target, value=value, rationale=rationale)
        )

    # ---- 硬负例块：40 条
    for index in range(40):
        text, scene, rationale = _NEGATIVE_TEMPLATES[index % len(_NEGATIVE_TEMPLATES)]
        counter += 1
        samples.append(_negative_case(text, scene, f"pref2_neg_{counter:04d}", rationale))

    _assert_block_consistency(samples)

    return {
        "metadata": {
            "dataset_id": f"memoryhub-preference-extraction-{SPEC_VERSION}",
            "version": "2.0.0",
            "created_at": created_at,
            "generator": GENERATOR_NAME,
            "generator_random_seed": seed,
            "spec_version": SPEC_VERSION,
            "label_source": LABEL_SOURCE,
            "sample_count": len(samples),
            "blocks": {
                "rule_hit": sum(1 for s in samples if s["block"] == "rule_hit"),
                "llm_required": sum(1 for s in samples if s["block"] == "llm_required"),
                "hard_negative": sum(1 for s in samples if s["block"] == "hard_negative"),
            },
            "annotation_rules": (
                "标签描述规格语义（类型 + payload target/value），非任何运行输出；"
                "rule_hit 必须命中规则、llm_required 必须不命中规则，由生成器机械校验。"
            ),
        },
        "samples": samples,
    }


def _assert_block_consistency(samples: list[dict[str, Any]]) -> None:
    """构建期机械校验块分类与实际规则行为一致。"""
    for sample in samples:
        rule_a, rule_b = rule_fires(sample["input_text"])
        if sample["block"] == "rule_hit":
            if not (rule_a or rule_b):
                raise ValueError(
                    f"{sample['case_id']} 标为 rule_hit 但规则未命中：{sample['input_text']!r}"
                )
        elif sample["block"] == "llm_required":
            if rule_a or rule_b:
                raise ValueError(
                    f"{sample['case_id']} 标为 llm_required 但规则会命中"
                    f"（A={rule_a} B={rule_b}）：{sample['input_text']!r}"
                )
        elif sample["block"] == "hard_negative":
            if rule_a or rule_b:
                raise ValueError(
                    f"{sample['case_id']} 标为 hard_negative 但规则会命中：{sample['input_text']!r}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 v2 偏好提取数据集")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--created-at", default=DEFAULT_CREATED_AT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    dataset = generate(created_at=args.created_at, seed=args.seed)
    output = args.output or OUTPUT_DIR / f"memoryhub_preference_extraction_{SPEC_VERSION}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **dataset["metadata"]["blocks"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
