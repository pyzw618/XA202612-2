"""精准遗忘模块（兼容入口）

注意：实际实现已迁移到 memoryhub.core.forget.forgetter。
本文件保留原导入路径，方便旧代码过渡。
"""

from memoryhub.core.forget.forgetter import MemoryForgetter

__all__ = ["MemoryForgetter"]

# MemoryForgetter 的真实实现位于 memoryhub.core.forget.forgetter
# 此处保持导入路径兼容。
