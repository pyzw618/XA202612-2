"""
模板构建模块

从历史案例中抽象出可复用的模板结构。
"""

from memoryhub.adapter.schemas import KnowledgeMemory


class TemplateBuilder:
    """模板构建器"""

    def build_from_case(self, case: KnowledgeMemory) -> KnowledgeMemory:
        """
        从历史案例中抽象出模板

        数据流:
            CASE 知识 → build_from_case → TEMPLATE 知识

        参数:
            case: CASE 类型的知识记忆

        返回:
            TEMPLATE 类型的 KnowledgeMemory

        处理逻辑:
            1. 分析案例的具体内容
            2. 将具体值替换为占位符
            3. 提取通用结构
            4. 生成模板正文
        """
        raise NotImplementedError

    def update_template(self, template_id: str, new_case: KnowledgeMemory) -> KnowledgeMemory:
        """
        用新案例更新已有模板

        参数:
            template_id: 已有模板 ID
            new_case: 新的案例

        返回:
            更新后的模板
        """
        raise NotImplementedError

    def render_template(self, template: KnowledgeMemory, variables: dict) -> str:
        """
        用具体变量渲染模板

        参数:
            template: 模板知识
            variables: 变量字典，如 {"project_name": "XX项目", "date": "2026-07-15"}

        返回:
            渲染后的文本
        """
        raise NotImplementedError
