"""
数据控制器 — 支持 Mock / Live 双模式

环境变量 MEMORYHUB_LIVE_BACKEND=1 时走真实 API，否则使用 Mock 数据。
UI 层（页面）无需感知切换，信号接口完全一致。

使用方式:
    controller = MockDataController(client=MemoryHubClient())
    controller.preferences_ready.connect(ui.on_data_loaded)
    controller.load_preferences()
"""

import os
import random
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from console.api_client import MemoryHubClient


def _simulate_latency(ms: int = 300):
    """模拟后端延迟（默认 300ms，满足比赛 ≤500ms 要求）"""
    time.sleep(ms / 1000)


def _is_error(data) -> bool:
    """检查 API 返回是否为错误"""
    return isinstance(data, dict) and "error" in data


# ---- API 数据归一化（将后端字段名映射为前端期望格式）----

def _normalize_preference(p: dict) -> dict:
    """归一化单条偏好记忆 — 后端 text → 前端 content"""
    if "text" in p and "content" not in p:
        p["content"] = p["text"]
    # 确保 scope 是 dict（Pydantic SceneScope 会序列化为 dict，但保险起见）
    if not isinstance(p.get("scope"), dict):
        p["scope"] = {"scene": "", "task_type": ""}
    # evidences: 确保是 list[dict]
    evidences = p.get("evidences", [])
    normalized_evidences = []
    for e in evidences:
        if isinstance(e, dict):
            normalized_evidences.append({
                "content": e.get("content", ""),
                "timestamp": str(e.get("timestamp", ""))[:10],
            })
    p["evidences"] = normalized_evidences
    # 确保 datetime 字段是字符串
    for key in ("created_at", "updated_at"):
        val = p.get(key)
        if val is not None and not isinstance(val, str):
            p[key] = str(val)
    return p


def _normalize_knowledge(k: dict) -> dict:
    """归一化单条知识记忆"""
    if not isinstance(k.get("scope"), dict):
        k["scope"] = {"scene": "", "task_type": ""}
    for key in ("created_at", "updated_at"):
        val = k.get(key)
        if val is not None and not isinstance(val, str):
            k[key] = str(val)
    return k


def _normalize_conflict(c: dict) -> dict:
    """归一化单条冲突记录"""
    for key in ("created_at", "resolved_at"):
        val = c.get(key)
        if val is not None and not isinstance(val, str):
            c[key] = str(val)
    return c


class MockDataController(QObject):
    """数据控制器 — Mock / Live 双模式"""

    # ---- 信号定义 ----
    dashboard_stats_ready = pyqtSignal(dict)
    preferences_ready = pyqtSignal(list)
    preference_detail_ready = pyqtSignal(dict)
    preference_versions_ready = pyqtSignal(list)
    knowledge_ready = pyqtSignal(list)
    knowledge_detail_ready = pyqtSignal(dict)
    conflicts_ready = pyqtSignal(list)
    search_results_ready = pyqtSignal(dict)
    forget_result_ready = pyqtSignal(dict)
    forget_history_ready = pyqtSignal(list)
    eval_reports_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, client: "MemoryHubClient | None" = None):
        super().__init__()
        self._client = client

    @property
    def _is_live(self) -> bool:
        """是否使用真实后端 API"""
        return os.environ.get("MEMORYHUB_LIVE_BACKEND", "") == "1" and self._client is not None

    # ============================================================
    # Dashboard
    # ============================================================

    def load_dashboard_stats(self):
        """异步加载 Dashboard 统计数据"""
        if self._is_live:
            def _run():
                try:
                    # Dashboard 暂无专用 API，聚合多个接口
                    prefs = self._client.list_preferences(status="")
                    knows = self._client.list_knowledge()
                    conflicts = self._client.list_conflicts(status="")
                    reports = self._client.list_eval_reports()

                    pref_list = prefs if isinstance(prefs, list) else []
                    know_list = knows if isinstance(knows, list) else []
                    conf_list = conflicts if isinstance(conflicts, list) else []

                    active_prefs = [p for p in pref_list if p.get("status") == "active"]
                    archived_prefs = [p for p in pref_list if p.get("status") == "archived"]
                    pending_confs = [c for c in conf_list if c.get("decision") == "pending"]

                    # 类型分布
                    pref_type_dist: dict[str, int] = {}
                    for p in pref_list:
                        t = p.get("preference_type", "other")
                        pref_type_dist[t] = pref_type_dist.get(t, 0) + 1

                    know_type_dist: dict[str, int] = {}
                    for k in know_list:
                        t = k.get("knowledge_type", "other")
                        know_type_dist[t] = know_type_dist.get(t, 0) + 1

                    stats = {
                        "total_memories": len(pref_list) + len(know_list),
                        "preference_count": len(pref_list),
                        "knowledge_count": len(know_list),
                        "conflict_count": len(pending_confs),
                        "active_preferences": len(active_prefs),
                        "archived_preferences": len(archived_prefs),
                        "avg_latency_ms": 0,
                        "latency_history": [],
                        "preference_type_dist": [
                            {"type": k, "count": v} for k, v in pref_type_dist.items()
                        ],
                        "knowledge_type_dist": [
                            {"type": k, "count": v} for k, v in know_type_dist.items()
                        ],
                    }
                    self.dashboard_stats_ready.emit(stats)
                except Exception as e:
                    self.error_occurred.emit(f"Dashboard 加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(250)
            self.dashboard_stats_ready.emit({
                "total_memories": 128,
                "preference_count": 47,
                "knowledge_count": 56,
                "conflict_count": 3,
                "active_preferences": 42,
                "archived_preferences": 5,
                "avg_latency_ms": 187.5,
                "latency_history": [
                    {"date": "07-24", "ms": 210},
                    {"date": "07-25", "ms": 185},
                    {"date": "07-26", "ms": 172},
                    {"date": "07-27", "ms": 198},
                    {"date": "07-28", "ms": 165},
                    {"date": "07-29", "ms": 190},
                    {"date": "07-30", "ms": 178},
                ],
                "preference_type_dist": [
                    {"type": "输出风格", "count": 15},
                    {"type": "工具选择", "count": 10},
                    {"type": "操作流程", "count": 8},
                    {"type": "安全策略", "count": 5},
                    {"type": "场景偏好", "count": 6},
                    {"type": "格式偏好", "count": 3},
                ],
                "knowledge_type_dist": [
                    {"type": "工作流", "count": 25},
                    {"type": "历史案例", "count": 18},
                    {"type": "模板", "count": 13},
                ],
            })
        Thread(target=_run, daemon=True).start()

    # ============================================================
    # 偏好记忆
    # ============================================================

    def load_preferences(self, scene: str = "", status: str = "active"):
        """异步加载偏好记忆列表"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.list_preferences(scene=scene, status=status)
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    items = data if isinstance(data, list) else []
                    items = [_normalize_preference(p) for p in items]
                    self.preferences_ready.emit(items)
                except Exception as e:
                    self.error_occurred.emit(f"偏好加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(300)
            samples = [
                {
                    "memory_id": "pref_a1b2c3d4",
                    "preference_type": "output_style",
                    "content": "项目周报默认使用 Markdown 格式，分三方面结构",
                    "scope": {"scene": "office", "task_type": "office.weekly_report"},
                    "confidence": 0.92,
                    "status": "active",
                    "level": "long",
                    "version": 3,
                    "evidences": [
                        {"content": "用户反馈：以后周报都用 Markdown", "timestamp": "2026-07-15"},
                        {"content": "重复选择 Markdown 模板 ×3", "timestamp": "2026-07-12"},
                    ],
                    "versions": [
                        {"version": 3, "content": "项目周报默认使用 Markdown 格式，分三方面结构", "change": "细化结构为三方面", "created_at": "2026-07-28"},
                        {"version": 2, "content": "项目周报默认使用 Markdown 格式", "change": "增加默认格式", "created_at": "2026-07-15"},
                        {"version": 1, "content": "周报偏好 Markdown", "change": "初始创建", "created_at": "2026-07-01"},
                    ],
                    "created_at": "2026-07-01T10:00:00",
                    "updated_at": "2026-07-28T14:30:00",
                },
                {
                    "memory_id": "pref_e5f6g7h8",
                    "preference_type": "tool_preference",
                    "content": "文件搜索任务优先使用本地检索工具而非网络搜索",
                    "scope": {"scene": "code", "task_type": "code.file_ops"},
                    "confidence": 0.85,
                    "status": "active",
                    "level": "long",
                    "version": 2,
                    "evidences": [
                        {"content": "连续 5 次选择本地检索", "timestamp": "2026-07-20"},
                    ],
                    "versions": [
                        {"version": 2, "content": "文件搜索优先本地检索工具", "change": "提高置信度至 0.85", "created_at": "2026-07-25"},
                        {"version": 1, "content": "文件搜索偏好本地工具", "change": "初始创建", "created_at": "2026-07-10"},
                    ],
                    "created_at": "2026-07-10T08:00:00",
                    "updated_at": "2026-07-25T16:00:00",
                },
                {
                    "memory_id": "pref_i9j0k1l2",
                    "preference_type": "safety_pref",
                    "content": "不保存 API Key、密码等敏感凭证信息",
                    "scope": {"scene": "*", "task_type": "*"},
                    "confidence": 1.0,
                    "status": "active",
                    "level": "long",
                    "version": 1,
                    "evidences": [
                        {"content": "手动配置：禁止保存 API Key", "timestamp": "2026-07-05"},
                    ],
                    "versions": [
                        {"version": 1, "content": "不保存 API Key、密码等敏感凭证信息", "change": "初始创建", "created_at": "2026-07-05"},
                    ],
                    "created_at": "2026-07-05T09:00:00",
                    "updated_at": "2026-07-05T09:00:00",
                },
                {
                    "memory_id": "pref_m3n4o5p6",
                    "preference_type": "format_pref",
                    "content": "代码注释使用中文，函数文档用英文",
                    "scope": {"scene": "code", "task_type": "code.documentation"},
                    "confidence": 0.78,
                    "status": "active",
                    "level": "mid",
                    "version": 1,
                    "evidences": [
                        {"content": "用户行为：代码注释始终使用中文", "timestamp": "2026-07-18"},
                    ],
                    "versions": [
                        {"version": 1, "content": "代码注释使用中文，函数文档用英文", "change": "初始创建", "created_at": "2026-07-18"},
                    ],
                    "created_at": "2026-07-18T11:00:00",
                    "updated_at": "2026-07-18T11:00:00",
                },
            ]
            self.preferences_ready.emit(samples)
        Thread(target=_run, daemon=True).start()

    def load_preference_detail(self, memory_id: str):
        """异步加载单条偏好详情"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.get_preference(memory_id)
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    self.preference_detail_ready.emit(_normalize_preference(data))
                except Exception as e:
                    self.error_occurred.emit(f"偏好详情加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(200)
            self.preference_detail_ready.emit({
                "memory_id": memory_id,
                "preference_type": "output_style",
                "content": "项目周报默认使用 Markdown 格式，分三方面结构",
                "scope": {"scene": "office", "task_type": "office.weekly_report"},
                "confidence": 0.92,
                "status": "active",
                "version": 3,
                "evidences": [
                    {"content": "用户反馈：以后周报都用 Markdown", "timestamp": "2026-07-15"},
                    {"content": "重复选择 Markdown 模板 ×3", "timestamp": "2026-07-12"},
                    {"content": "工具调用：report_writer 使用 Markdown", "timestamp": "2026-07-08"},
                ],
                "created_at": "2026-07-01T10:00:00",
                "updated_at": "2026-07-28T14:30:00",
            })
        Thread(target=_run, daemon=True).start()

    def load_preference_versions(self, memory_id: str):
        """异步加载版本历史"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.get_preference_versions(memory_id)
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    versions = data if isinstance(data, list) else []
                    # 归一化：确保 content 字段存在
                    for v in versions:
                        if "text" in v and "content" not in v:
                            v["content"] = v["text"]
                    self.preference_versions_ready.emit(versions)
                except Exception as e:
                    self.error_occurred.emit(f"版本历史加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(200)
            self.preference_versions_ready.emit([
                {"version": 3, "content": "项目周报默认使用 Markdown 格式，分三方面结构", "change": "细化结构为三方面", "created_at": "2026-07-28"},
                {"version": 2, "content": "项目周报默认使用 Markdown 格式", "change": "增加默认格式", "created_at": "2026-07-15"},
                {"version": 1, "content": "周报偏好 Markdown", "change": "初始创建", "created_at": "2026-07-01"},
            ])
        Thread(target=_run, daemon=True).start()

    # ============================================================
    # 知识记忆
    # ============================================================

    def load_knowledge(self, knowledge_type: str = ""):
        """异步加载知识记忆列表"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.list_knowledge(knowledge_type=knowledge_type)
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    items = data if isinstance(data, list) else []
                    items = [_normalize_knowledge(k) for k in items]
                    self.knowledge_ready.emit(items)
                except Exception as e:
                    self.error_occurred.emit(f"知识加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(300)
            samples = [
                {
                    "memory_id": "know_x1y2z3",
                    "knowledge_type": "workflow",
                    "name": "项目周报生成流程",
                    "content": "自动生成项目周报的完整工作流",
                    "steps": ["读取日历", "检索项目文件", "提取完成事项", "整理风险", "生成报告"],
                    "tools": ["calendar_query", "file_search", "doc_reader", "report_writer"],
                    "confidence": 0.88,
                    "success_count": 12,
                    "total_count": 15,
                    "status": "active",
                    "created_at": "2026-07-03T10:00:00",
                },
                {
                    "memory_id": "know_a4b5c6",
                    "knowledge_type": "case",
                    "name": "2026-07-28 项目周报案例",
                    "content": "最近一次成功的周报生成案例",
                    "steps": ["读取日历", "检索文件", "生成报告"],
                    "tools": ["calendar_query", "file_search", "report_writer"],
                    "confidence": 0.95,
                    "success_count": 1,
                    "total_count": 1,
                    "status": "active",
                    "created_at": "2026-07-28T14:00:00",
                },
                {
                    "memory_id": "know_d7e8f9",
                    "knowledge_type": "template",
                    "name": "三段式周报模板",
                    "content": "本周进展 / 问题风险 / 下周计划",
                    "template_body": "## 本周进展\n- ...\n## 问题风险\n- ...\n## 下周计划\n- ...",
                    "tools": [],
                    "confidence": 0.90,
                    "success_count": 8,
                    "total_count": 10,
                    "status": "active",
                    "created_at": "2026-07-05T09:00:00",
                },
            ]
            self.knowledge_ready.emit(samples)
        Thread(target=_run, daemon=True).start()

    # ============================================================
    # 冲突
    # ============================================================

    def load_conflicts(self):
        """异步加载冲突列表"""
        if self._is_live:
            def _run():
                try:
                    # 加载所有冲突（含已解决），前端自行筛选
                    data = self._client.list_conflicts(status="")
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    items = data if isinstance(data, list) else []
                    items = [_normalize_conflict(c) for c in items]
                    self.conflicts_ready.emit(items)
                except Exception as e:
                    self.error_occurred.emit(f"冲突加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(250)
            self.conflicts_ready.emit([
                {
                    "conflict_id": "conf_001",
                    "old_memory_id": "pref_old",
                    "new_memory_id": "pref_new",
                    "memory_type": "preference",
                    "old_content": "项目周报默认使用 Markdown",
                    "new_content": "以后周报改成 Word 格式",
                    "conflict_field": "content",
                    "decision": "pending",
                    "reason": "同场景下输出格式偏好冲突",
                    "created_at": "2026-07-29T15:00:00",
                },
                {
                    "conflict_id": "conf_002",
                    "new_memory_id": "pref_002",
                    "old_memory_id": "pref_003",
                    "memory_type": "preference",
                    "old_content": "写论文要正式详细",
                    "new_content": "写代码要简洁直接",
                    "conflict_field": "scope",
                    "decision": "coexist",
                    "reason": "不同场景，可并存",
                    "created_at": "2026-07-20T10:00:00",
                },
                {
                    "conflict_id": "conf_003",
                    "new_memory_id": "pref_004",
                    "old_memory_id": "pref_005",
                    "memory_type": "preference",
                    "old_content": "搜索文件优先使用本地工具",
                    "new_content": "搜索文件优先使用网络搜索",
                    "conflict_field": "content",
                    "decision": "override",
                    "reason": "用户明确要求更换搜索方式",
                    "created_at": "2026-07-18T09:30:00",
                },
                {
                    "conflict_id": "conf_004",
                    "new_memory_id": "pref_006",
                    "old_memory_id": "pref_007",
                    "memory_type": "preference",
                    "old_content": "代码注释使用中文",
                    "new_content": "代码注释使用英文",
                    "conflict_field": "content",
                    "decision": "pending",
                    "reason": "注释语言偏好冲突",
                    "created_at": "2026-07-30T11:00:00",
                },
            ])
        Thread(target=_run, daemon=True).start()

    def resolve_conflict(self, conflict_id: str, decision: str):
        """解决冲突 — Live 模式调用 API，Mock 模式仅更新内存"""
        if self._is_live:
            def _run():
                try:
                    result = self._client.resolve_conflict(conflict_id, decision)
                    if _is_error(result):
                        self.error_occurred.emit(result["error"])
                        return
                    # 解决成功后重新加载冲突列表
                    self.load_conflicts()
                except Exception as e:
                    self.error_occurred.emit(f"冲突解决失败: {e}")
            Thread(target=_run, daemon=True).start()

    # ============================================================
    # 检索
    # ============================================================

    def search(self, query: str, context: dict | None = None):
        """异步执行检索"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.search(query=query, context=context)
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    # 归一化检索结果
                    prefs = [_normalize_preference(p) for p in data.get("preferences", [])]
                    knows = [_normalize_knowledge(k) for k in data.get("knowledge", [])]
                    self.search_results_ready.emit({
                        "query": query,
                        "latency_ms": data.get("latency_ms", 0),
                        "preferences": prefs,
                        "knowledge": knows,
                        "total_count": data.get("total_count", len(prefs) + len(knows)),
                    })
                except Exception as e:
                    self.error_occurred.emit(f"检索失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            start = time.time()
            _simulate_latency(200)
            elapsed = (time.time() - start) * 1000
            self.search_results_ready.emit({
                "query": query,
                "latency_ms": round(elapsed, 1),
                "preferences": [
                    {"memory_id": "pref_a1b2c3d4", "content": "项目周报默认使用 Markdown 格式", "score": 0.94, "type": "preference"},
                    {"memory_id": "pref_e5f6g7h8", "content": "文件搜索优先本地检索", "score": 0.72, "type": "preference"},
                ],
                "knowledge": [
                    {"memory_id": "know_x1y2z3", "name": "项目周报生成流程", "score": 0.91, "type": "knowledge"},
                    {"memory_id": "know_d7e8f9", "name": "三段式周报模板", "score": 0.85, "type": "knowledge"},
                ],
            })
        Thread(target=_run, daemon=True).start()

    # ============================================================
    # 遗忘
    # ============================================================

    def forget(self, instruction: str):
        """异步执行遗忘"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.forget(instruction=instruction)
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    self.forget_result_ready.emit(data)
                except Exception as e:
                    self.error_occurred.emit(f"遗忘失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(400)
            self.forget_result_ready.emit({
                "record_id": f"forg_{random.randint(1000, 9999)}",
                "deleted_count": 1,
                "deleted_ids": ["pref_a1b2c3d4"],
                "audit_log": f"已删除与「{instruction}」相关的偏好记忆 1 条",
            })
        Thread(target=_run, daemon=True).start()

    def load_forget_history(self):
        """异步加载遗忘历史"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.get_forget_history()
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    items = data if isinstance(data, list) else []
                    self.forget_history_ready.emit(items)
                except Exception as e:
                    self.error_occurred.emit(f"遗忘历史加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(200)
            self.forget_history_ready.emit([
                {"record_id": "forg_1001", "instruction": "忘掉周报格式偏好", "deleted_count": 1, "created_at": "2026-07-29 15:30"},
                {"record_id": "forg_1000", "instruction": "删除项目A的历史记录", "deleted_count": 3, "created_at": "2026-07-25 10:00"},
            ])
        Thread(target=_run, daemon=True).start()

    # ============================================================
    # 评测
    # ============================================================

    def load_eval_reports(self):
        """异步加载评测报告"""
        if self._is_live:
            def _run():
                try:
                    data = self._client.list_eval_reports()
                    if _is_error(data):
                        self.error_occurred.emit(data["error"])
                        return
                    items = data if isinstance(data, list) else []
                    self.eval_reports_ready.emit(items)
                except Exception as e:
                    self.error_occurred.emit(f"评测报告加载失败: {e}")
            Thread(target=_run, daemon=True).start()
            return

        def _run():
            _simulate_latency(300)
            self.eval_reports_ready.emit([
                {
                    "task_name": "preference_extraction",
                    "total_samples": 200,
                    "accuracy": 0.89,
                    "precision": 0.87,
                    "recall": 0.91,
                    "f1": 0.89,
                    "avg_latency_ms": 145.2,
                    "p95_latency_ms": 298.5,
                },
                {
                    "task_name": "retrieval",
                    "total_samples": 300,
                    "accuracy": 0.0,
                    "recall_at_k": 0.88,
                    "mrr": 0.82,
                    "avg_latency_ms": 187.5,
                    "p95_latency_ms": 420.0,
                },
                {
                    "task_name": "conflict",
                    "total_samples": 50,
                    "accuracy": 0.92,
                    "avg_latency_ms": 95.0,
                    "p95_latency_ms": 180.0,
                },
            ])
        Thread(target=_run, daemon=True).start()
