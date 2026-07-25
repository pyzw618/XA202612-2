"""版本化安全规则库的异常类型。"""


class RuleLibraryError(ValueError):
    """规则库内容、组件引用或调用参数无效。"""


class RuleSetNotFoundError(RuleLibraryError):
    """请求的内置规则集版本不存在。"""


class RuleIntegrityError(RuleLibraryError):
    """规则资源无法完整、无歧义地解析或摘要不匹配。"""
