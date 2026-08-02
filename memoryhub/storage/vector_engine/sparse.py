"""
稀疏向量生成（Python 侧）。

决策说明：方案文档（阶段 5）原本建议使用 jieba 分词生成稀疏向量，
但稀疏向量的索引/权重必须与 C 桥接层（及 mock 动态库）内部对
content 生成的稀疏向量逐位一致，否则 hybrid_search 的稀疏路对不上。
jieba 的分词粒度与 C 侧逐字符规则无法对齐，因此放弃 jieba，
改为与 C 实现（third_party/kylin-mock/vector_engine_mock.c 中的
sparse_from_text）完全相同的规则：

- ASCII 字母/数字连写为一个 token（**保留原始大小写**，与 C 侧一致；
  C 实现直接对原始字节做 hash，不做小写转换）；
- 其余所有非 ASCII 字符（含中文等）每个字符单独成一个 token；
- 空白和标点仅作分隔符；
- token 索引 = FNV-1a 32-bit hash（offset basis 2166136261，
  prime 16777619，对 UTF-8 字节序列计算）；
- 权重 = token 出现次数 / 总 token 数（归一化 TF），同一索引的
  计数累加（与 C 侧 accum_token 行为一致）；
- 返回按索引升序排序的 [(index, weight), ...]。
"""

_FNV_OFFSET_BASIS = 2166136261
_FNV_PRIME = 16777619
_UINT32_MASK = 0xFFFFFFFF


def _fnv1a32(data: bytes) -> int:
    """FNV-1a 32-bit hash，与 C 侧 fnv1a32 逐位一致。"""
    h = _FNV_OFFSET_BASIS
    for byte in data:
        h ^= byte
        h = (h * _FNV_PRIME) & _UINT32_MASK
    return h


def _is_alnum_ascii(ch: str) -> bool:
    return ("0" <= ch <= "9") or ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def build_sparse_vector(text: str) -> list[tuple[int, float]]:
    """
    从文本构建稀疏向量，规则与 C 桥接层逐位一致。

    参数:
        text: 输入文本

    返回:
        [(token 索引, 权重), ...]，按索引升序；空文本返回空列表
    """
    counts: dict[int, int] = {}
    total = 0

    current: list[str] = []  # 当前 ASCII 字母/数字连写 token

    def flush_current() -> None:
        nonlocal total
        if not current:
            return
        token = "".join(current)
        current.clear()
        h = _fnv1a32(token.encode("utf-8"))
        counts[h] = counts.get(h, 0) + 1
        total += 1

    for ch in text:
        if ord(ch) < 0x80:
            if _is_alnum_ascii(ch):
                current.append(ch)
            else:
                # 空白/标点：分隔符
                flush_current()
        else:
            # 非 ASCII 字符（含中文）：单字成 token
            flush_current()
            h = _fnv1a32(ch.encode("utf-8"))
            counts[h] = counts.get(h, 0) + 1
            total += 1
    flush_current()

    if total == 0:
        return []

    return sorted(
        ((index, count / total) for index, count in counts.items()),
        key=lambda item: item[0],
    )
