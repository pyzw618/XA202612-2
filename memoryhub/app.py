"""
FastAPI 应用入口

组装所有模块，启动本地 Memory Service。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from memoryhub.config import AppConfig, load_config
from memoryhub.adapter.api import router as memory_router


def create_app(config: AppConfig | None = None) -> FastAPI:
    """
    创建 FastAPI 应用

    参数:
        config: 应用配置，为 None 时使用默认配置

    返回:
        FastAPI 实例

    初始化流程:
        1. 加载配置
        2. 初始化存储层（SQLite + FAISS）
        3. 初始化 LLM / Embedding 客户端
        4. 注册路由
        5. 注册生命周期钩子
    """
    if config is None:
        config = load_config()

    app = FastAPI(
        title="Kylin-MemoryHub",
        description="面向麒麟 OS Agent 的可插拔本地记忆中枢",
        version="0.1.0",
    )

    # CORS（开发时允许前端跨域）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(memory_router)

    # 注册生命周期
    @app.on_event("startup")
    async def startup():
        """应用启动时初始化各组件"""
        # TODO: 初始化数据库、向量索引、LLM 客户端等
        pass

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时释放资源"""
        # TODO: 关闭数据库连接、保存向量索引等
        pass

    return app


# 用于直接运行: uvicorn memoryhub.app:app --reload
app = create_app()
