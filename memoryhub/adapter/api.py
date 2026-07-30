"""
REST API 路由定义 — Memory Adapter 标准接口

所有接口均通过 FastAPI 路由暴露，供 OS Agent 或前端调用。
"""

from fastapi import APIRouter, HTTPException, Request

from memoryhub.adapter.schemas import (
    ForgetRequest,
    ForgetResponse,
    FeedbackRequest,
    SearchRequest,
    SearchResponse,
    WriteEventRequest,
    WriteEventResponse,
    PreferenceMemory,
    KnowledgeMemory,
    ConflictRecord,
    ForgetRecord,
    EvalReport,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ============================================================
# 事件写入
# ============================================================

@router.post("/events", response_model=WriteEventResponse)
async def write_events(req: WriteEventRequest):
    """
    写入多源事件数据

    数据流: OS Agent → write_events → Ingestion.clean → Ingestion.normalize
            → 存入事件库 → 触发偏好/知识抽取

    参数:
        req.events: MemoryEvent 列表

    返回:
        accepted: 成功接收的事件数
        rejected: 被拒绝的事件数（质量/安全过滤）
        event_ids: 接受的事件 ID 列表
    """
    raise NotImplementedError


# ============================================================
# 记忆检索
# ============================================================

@router.post("/search", response_model=SearchResponse)
async def search_memory(req: SearchRequest, request: Request):
    """
    混合检索偏好与知识记忆

    数据流: OS Agent → search_memory → HybridRetriever.search
            → (vector_recall + keyword_recall + metadata_filter)
            → rerank → 返回 Top-K

    参数:
        req.query: 检索查询文本
        req.context: 场景作用域过滤
        req.top_k: 返回结果数
        req.memory_types: 过滤记忆类型 ["preference", "knowledge"]
        req.min_confidence: 最低置信度阈值

    返回:
        preferences: 匹配的偏好记忆列表
        knowledge: 匹配的知识记忆列表
        latency_ms: 检索耗时
    """
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None:
        raise HTTPException(status_code=503, detail="retrieval service not initialized")
    try:
        return retriever.search(req)
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid search request") from None
    except Exception:
        # 不回显内部异常细节，避免泄露输入内容或实现信息
        raise HTTPException(status_code=500, detail="internal retrieval error") from None


@router.post("/context")
async def get_memory_context(req: SearchRequest):
    """
    获取可直接拼接进 Agent 上下文的记忆摘要

    与 search_memory 类似，但返回格式为可直接注入 prompt 的文本。

    数据流: OS Agent → get_memory_context → search_memory
            → 格式化为上下文文本 → 返回
    """
    raise NotImplementedError


# ============================================================
# 偏好管理
# ============================================================

@router.get("/preferences", response_model=list[PreferenceMemory])
async def list_preferences(
    user_id: str = "default",
    scene: str = "",
    status: str = "active",
):
    """列出偏好记忆，支持按场景和状态过滤"""
    raise NotImplementedError


@router.get("/preferences/{memory_id}", response_model=PreferenceMemory)
async def get_preference(memory_id: str):
    """获取单条偏好记忆详情"""
    raise NotImplementedError


@router.get("/preferences/{memory_id}/versions")
async def get_preference_versions(memory_id: str):
    """获取偏好记忆的版本历史链"""
    raise NotImplementedError


# ============================================================
# 知识管理
# ============================================================

@router.get("/knowledge", response_model=list[KnowledgeMemory])
async def list_knowledge(
    user_id: str = "default",
    scene: str = "",
    knowledge_type: str = "",
):
    """列出知识记忆，支持按类型和场景过滤"""
    raise NotImplementedError


@router.get("/knowledge/{memory_id}", response_model=KnowledgeMemory)
async def get_knowledge(memory_id: str):
    """获取单条知识记忆详情"""
    raise NotImplementedError


# ============================================================
# 冲突管理
# ============================================================

@router.get("/conflicts", response_model=list[ConflictRecord])
async def list_conflicts(status: str = "pending"):
    """列出冲突记录，支持按状态过滤"""
    raise NotImplementedError


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, decision: str, reason: str = ""):
    """
    手动解决待确认冲突

    数据流: 用户确认 → resolve_conflict → ConflictResolver.resolve
            → 更新记忆 → 记录 ConflictRecord
    """
    raise NotImplementedError


# ============================================================
# 用户反馈
# ============================================================

@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """
    提交用户反馈，触发偏好更新

    数据流: 用户反馈 → submit_feedback → PreferenceExtractor.extract
            → ConflictDetector.check → 更新/新增偏好

    参数:
        req.memory_id: 关联的记忆 ID
        req.feedback_text: 反馈文本
        req.action: "update" | "confirm" | "reject"
    """
    raise NotImplementedError


# ============================================================
# 精准遗忘
# ============================================================

@router.post("/forget", response_model=ForgetResponse)
async def forget_memory(req: ForgetRequest):
    """
    自然语言驱动的精准遗忘

    数据流: 用户指令 → forget_memory → LLM 解析意图
            → 定位记忆 → 删除 SQLite + FAISS + 缓存
            → 生成审计日志

    参数:
        req.instruction: 自然语言指令，如 "忘掉我关于周报格式的偏好"
        req.target_scope: 可选的场景范围限制
    """
    raise NotImplementedError


@router.get("/forget/history", response_model=list[ForgetRecord])
async def list_forget_history(user_id: str = "default"):
    """列出遗忘操作历史"""
    raise NotImplementedError


# ============================================================
# 评测
# ============================================================

@router.post("/evaluate/{task_name}", response_model=EvalReport)
async def run_evaluation(task_name: str, dataset_path: str = ""):
    """
    运行指定任务的评测

    task_name: "preference" | "retrieval" | "conflict" | "latency"

    数据流: 触发评测 → 加载数据集 → 批量执行 → 计算指标 → 生成报告
    """
    raise NotImplementedError


@router.get("/evaluate/reports", response_model=list[EvalReport])
async def list_eval_reports():
    """列出历史评测报告"""
    raise NotImplementedError
