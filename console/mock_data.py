"""
Mock 数据控制器

封装所有模拟数据，通过信号暴露给 UI 层。
后端就绪后，替换为真实 API 调用即可，UI 层无需改动。

使用方式:
    controller = MockDataController()
    controller.data_ready.connect(ui.on_data_loaded)
    controller.load_dashboard_stats()
"""

import random
import time
from datetime import datetime, timedelta
from threading import Thread

from PyQt6.QtCore import QObject, pyqtSignal


def _simulate_latency(ms: int = 300):
    """模拟后端延迟（默认 300ms，满足比赛 ≤500ms 要求）"""
    time.sleep(ms / 1000)


class MockDataController(QObject):
    """Mock 数据控制器 — 所有数据操作统一入口"""

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

    # ============================================================
    # Dashboard
    # ============================================================

    def load_dashboard_stats(self):
        """异步加载 Dashboard 统计数据"""
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
        def _run():
            _simulate_latency(300)
            samples = [
                {
                    "memory_id": "pref_a1b2c3d4",
                    "preference_type": "output_style",
                    "content": "项目周报默认使用 Markdown 格式，分三部分结构",
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
                        {"version": 3, "content": "项目周报默认使用 Markdown 格式，分三部分结构", "change": "细化结构为三部分", "created_at": "2026-07-28"},
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
        def _run():
            _simulate_latency(200)
            self.preference_detail_ready.emit({
                "memory_id": memory_id,
                "preference_type": "output_style",
                "content": "项目周报默认使用 Markdown 格式，分三部分结构",
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
        def _run():
            _simulate_latency(200)
            self.preference_versions_ready.emit([
                {"version": 3, "content": "项目周报默认使用 Markdown 格式，分三部分结构", "change": "细化结构为三部分", "created_at": "2026-07-28"},
                {"version": 2, "content": "项目周报默认使用 Markdown 格式", "change": "增加默认格式", "created_at": "2026-07-15"},
                {"version": 1, "content": "周报偏好 Markdown", "change": "初始创建", "created_at": "2026-07-01"},
            ])
        Thread(target=_run, daemon=True).start()

    # ============================================================
    # 知识记忆
    # ============================================================

    def load_knowledge(self, knowledge_type: str = ""):
        """异步加载知识记忆列表"""
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

    # ============================================================
    # 检索
    # ============================================================

    def search(self, query: str, context: dict | None = None):
        """异步执行检索"""
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