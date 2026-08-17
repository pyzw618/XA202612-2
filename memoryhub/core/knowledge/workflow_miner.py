"""
工作流挖掘模块
从多次任务执行中挖掘稳定的工作流模式。
采用 LCS 规则优先 + LLM 语义兜底的双引擎架构。
"""
from __future__ import annotations

import logging
import re

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    SceneScope,
)
from memoryhub.core.knowledge._event_utils import (
    coerce_event as _coerce_event,
)
from memoryhub.core.knowledge._event_utils import (
    event_content as _event_content,
)
from memoryhub.core.knowledge._event_utils import (
    event_quality_score as _event_quality_score,
)
from memoryhub.core.knowledge._event_utils import (
    event_timestamp as _event_timestamp,
)
from memoryhub.core.knowledge._event_utils import (
    evidence_source_type as _evidence_source_type,
)
from memoryhub.core.knowledge._event_utils import (
    get_event_field as _get_event_field,
)
from memoryhub.core.knowledge._event_utils import (
    get_event_type as _get_event_type,
)
from memoryhub.core.knowledge._event_utils import (
    normalize_step as _normalize_step,
)

logger = logging.getLogger(__name__)


class WorkflowMiner:
    """工作流挖掘器"""

    def __init__(self, llm_client=None):
        """
        参数:
            llm_client: LLM 抽象客户端，用于语义辅助挖掘，可选
        """
        self.llm_client = llm_client
        # LLM 触发阈值
        self._min_anchor_ratio = 0.3  # 锚点长度占平均序列长度最小比例
        self._min_stability = 0.6     # 最小稳定度阈值
        self._min_pattern_steps = 2   # 公共模式最少步骤数

    def mine(self, task_groups: list[list[MemoryEvent | dict]]) -> list[KnowledgeMemory]:
        """
        从多组同类任务轨迹中挖掘工作流。
        内部采用 LCS 优先 + LLM 兜底的混合策略，对外接口保持不变。
        """
        if not task_groups:
            return []

        # 前置过滤：剔除平均质量过低的任务组
        valid_groups = []
        for group in task_groups:
            if not group:
                continue
            normalized_group = [_coerce_event(event) for event in group]
            normalized_group = [event for event in normalized_group if event is not None]
            if not normalized_group:
                continue
            avg_quality = sum(_event_quality_score(event) for event in normalized_group) / len(normalized_group)
            if avg_quality >= 0.3:
                valid_groups.append(normalized_group)
        if not valid_groups:
            return []

        step_sequences: list[list[str]] = []
        tool_counter: dict[str, int] = {}
        events_for_evidence: list[MemoryEvent] = []

        for group in valid_groups:
            steps = self._extract_steps(group)
            if steps:
                step_sequences.append(steps)
            for event in group:
                events_for_evidence.append(event)
                content = _event_content(event)
                if _get_event_type(event) == "task_trajectory":
                    for tool in content.get("tools") or []:
                        value = str(tool).strip()
                        if value:
                            tool_counter[value] = tool_counter.get(value, 0) + 1

        if not step_sequences:
            return []

        # 工具链：保留出现频率≥50%的工具，按频率降序排列
        total_groups = len(valid_groups)
        tools = [tool for tool, count in tool_counter.items() if count / total_groups >= 0.5]
        tools.sort(key=lambda x: tool_counter[x], reverse=True)

        # ========== 阶段1：LCS 规则挖掘 ==========
        aligned = self._align_steps(step_sequences)
        common_pattern = self._extract_common_pattern(aligned)
        if not common_pattern:
            common_pattern = step_sequences[0]
        stability = self._calculate_stability(common_pattern, step_sequences)

        # ========== 阶段2：效果评估，判断是否触发 LLM ==========
        need_llm = self._should_invoke_llm(common_pattern, step_sequences, stability)

        # ========== 阶段3：LLM 语义辅助挖掘（条件触发）==========
        if need_llm and self.llm_client and self.llm_client.is_available():
            llm_pattern = self._llm_mine_pattern(step_sequences)
            if llm_pattern and len(llm_pattern) >= self._min_pattern_steps:
                common_pattern = llm_pattern
                # 重新计算稳定度
                stability = self._calculate_stability(common_pattern, step_sequences)
            # LLM 调用失败或结果无效，自动沿用 LCS 结果，不中断流程

        first_event = next((event for group in valid_groups if group for event in group), None)
        if first_event is None:
            return []

        return [
            KnowledgeMemory(
                user_id=_get_event_field(first_event, "user_id", "default"),
                knowledge_type=KnowledgeType.WORKFLOW,
                name=f"{_get_event_field(first_event, 'task_id', '任务')}工作流",
                content="从多次执行轨迹中提炼出的稳定步骤序列",
                steps=common_pattern,
                tools=tools,
                scope=SceneScope(
                    scene=_get_event_field(first_event, "scene", ""),
                    task_type=_get_event_field(first_event, "task_type", ""),
                    app=_get_event_field(first_event, "source", _get_event_field(first_event, "source_type", "")),
                ),
                confidence=stability,
                success_count=max(1, len(step_sequences)),
                total_count=max(1, len(step_sequences)),
                status=MemoryStatus.ACTIVE,
                level=MemoryLevel.MID,
                evidences=self._build_evidences(events_for_evidence),
            )
        ]

    def _should_invoke_llm(self, pattern: list[str], sequences: list[list[str]], stability: float) -> bool:
        """判断是否需要触发 LLM 辅助挖掘"""
        if not pattern or len(pattern) < self._min_pattern_steps:
            return True
        if stability < self._min_stability:
            return True

        # 计算全局 LCS 锚点占比
        avg_len = sum(len(seq) for seq in sequences) / len(sequences)
        if avg_len == 0:
            return False
        anchor_len = len(self._get_global_anchor(sequences))
        if anchor_len / avg_len < self._min_anchor_ratio:
            return True

        # 步骤数量差异过大（粒度不一致）
        max_len = max(len(seq) for seq in sequences)
        min_len = min(len(seq) for seq in sequences)
        if min_len > 0 and max_len / min_len > 2:
            return True

        return False

    def _get_global_anchor(self, sequences: list[list[str]]) -> list[str]:
        """获取所有序列的全局 LCS 锚点"""
        if not sequences:
            return []
        anchor = sequences[0]
        for seq in sequences[1:]:
            anchor = self._lcs_sequence(anchor, seq)
            if not anchor:
                break
        return anchor

    def _llm_mine_pattern(self, sequences: list[list[str]]) -> list[str]:
        """
        LLM 辅助挖掘公共工作流模式。
        输入多条步骤序列，输出语义归纳后的标准步骤列表。
        """
        # 构造 prompt
        sequences_text = "\n".join(
            f"第{i+1}条执行轨迹：{' → '.join(seq)}"
            for i, seq in enumerate(sequences)
        )
        prompt = f"""
你是工作流挖掘专家。请从以下多条同类任务的执行轨迹中，归纳出一条通用的标准执行流程。
要求：
1. 提取所有轨迹共有的核心步骤，剔除偶发、调试类的异常步骤
2. 语义等价的步骤做归一化合并，保留统一的规范表述
3. 按执行的先后逻辑排序，步骤简洁清晰，每条不超过20字
4. 只返回步骤列表的 JSON 格式，格式为 {{"steps": ["步骤1", "步骤2", ...]}}
5. 不要输出任何额外解释文字

执行轨迹：
{sequences_text}
"""

        try:
            # 调用 LLM 结构化输出接口（匹配项目 BaseLLMClient 抽象）
            result = self.llm_client.generate_json(
                prompt=prompt,
                schema={"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}}},
                system_prompt="你是专业的流程分析专家，擅长从多条执行记录中提炼标准化工作流。"
            )
            steps = result.get("steps", [])
            # 结果校验：必须是非空列表，且为字符串
            if isinstance(steps, list) and steps and all(isinstance(s, str) and s.strip() for s in steps):
                # 做归一化处理，统一格式
                return [_normalize_step(s.strip()) for s in steps if s.strip()]
            return []
        except Exception as exc:
            # LLM 调用异常直接返回空，外层自动降级为 LCS 结果
            logger.warning("LLM workflow enrichment failed, falling back to LCS: %s", exc)
            return []

    def _align_steps(self, step_sequences: list[list[str]]) -> list[list[str]]:
        """基于最长公共子序列(LCS)对齐多条步骤序列"""
        if not step_sequences:
            return []
        if len(step_sequences) == 1:
            return step_sequences

        # 迭代求所有序列的全局公共锚点
        anchor = self._get_global_anchor(step_sequences)
        if not anchor:
            return step_sequences  # 无公共子序列，返回原始序列

        # 基于锚点对齐每个序列
        aligned = []
        for seq in step_sequences:
            aligned_seq = []
            seq_idx = 0
            anchor_idx = 0
            while seq_idx < len(seq) and anchor_idx < len(anchor):
                if seq[seq_idx] == anchor[anchor_idx]:
                    aligned_seq.append(seq[seq_idx])
                    seq_idx += 1
                    anchor_idx += 1
                else:
                    aligned_seq.append(seq[seq_idx])
                    seq_idx += 1
            # 追加剩余步骤
            while seq_idx < len(seq):
                aligned_seq.append(seq[seq_idx])
                seq_idx += 1
            aligned.append(aligned_seq)
        return aligned

    def _extract_common_pattern(self, aligned: list[list[str]]) -> list[str]:
        """提取公共模式：保留出现频率≥50%的核心步骤"""
        if not aligned:
            return []
        max_len = max(len(seq) for seq in aligned)
        pattern: list[str] = []
        total = len(aligned)

        for idx in range(max_len):
            step_counts: dict[str, int] = {}
            for seq in aligned:
                if idx < len(seq):
                    step = seq[idx]
                    step_counts[step] = step_counts.get(step, 0) + 1

            if not step_counts:
                continue

            # 取该位置最高频步骤，出现率≥50%则保留
            top_step, count = max(step_counts.items(), key=lambda x: x[1])
            if count / total >= 0.5:
                # 避免连续重复步骤
                if not pattern or pattern[-1] != top_step:
                    pattern.append(top_step)

        return pattern

    def _calculate_stability(self, steps: list[str], all_sequences: list[list[str]]) -> float:
        """计算工作流稳定度：基于序列LCS相似度"""
        if not steps or not all_sequences:
            return 0.0

        lcs_ratios = []
        for seq in all_sequences:
            lcs_len = self._lcs_length(steps, seq)
            ratio = lcs_len / max(len(steps), len(seq), 1)
            lcs_ratios.append(ratio)

        avg_ratio = sum(lcs_ratios) / len(lcs_ratios)
        stability = 0.6 + 0.4 * avg_ratio
        return round(min(0.95, stability), 4)

    def _extract_steps(self, events: list[MemoryEvent | dict]) -> list[str]:
        steps: list[str] = []
        seen: set[str] = set()
        for event in events:
            content = _event_content(event)
            raw_steps = content.get("steps") or []
            if isinstance(raw_steps, list):
                for step in raw_steps:
                    value = _normalize_step(str(step).strip())
                    if value and value not in seen and len(value) >= 2:
                        steps.append(value)
                        seen.add(value)
        return steps

    def _normalize_step(self, step: str) -> str:
        """步骤文本归一化，与抽取器保持一致"""
        step = re.sub(r'^\s*(第[一二三四五六七八九十\d]+[步、：:.]\s*)', '', step)
        step = re.sub(r'^\s*\d+[.、\s]+', '', step)
        return step.strip(' 。，、：:.')

    def _lcs_length(self, seq1: list[str], seq2: list[str]) -> int:
        """计算两个序列的最长公共子序列长度"""
        m, n = len(seq1), len(seq2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq1[i - 1] == seq2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
        return dp[m][n]

    def _lcs_sequence(self, seq1: list[str], seq2: list[str]) -> list[str]:
        """获取两个序列的最长公共子序列"""
        m, n = len(seq1), len(seq2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq1[i - 1] == seq2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        # 回溯还原LCS
        lcs = []
        i, j = m, n
        while i > 0 and j > 0:
            if seq1[i - 1] == seq2[j - 1]:
                lcs.append(seq1[i - 1])
                i -= 1
                j -= 1
            elif dp[i - 1][j] > dp[i][j - 1]:
                i -= 1
            else:
                j -= 1
        return lcs[::-1]

    def _build_evidences(self, events: list[MemoryEvent | dict]) -> list[Evidence]:
        evidences: list[Evidence] = []
        for event in events:
            weight = 0.85 if _get_event_type(event) == "task_trajectory" else 0.75
            evidences.append(
                Evidence(
                    event_id=_get_event_field(event, "event_id", ""),
                    content=f"轨迹 {_get_event_field(event, 'task_id', _get_event_field(event, 'event_id', ''))}",
                    source_type=_evidence_source_type(event),
                    timestamp=_event_timestamp(event),
                    weight=weight,
                )
            )
        return evidences
