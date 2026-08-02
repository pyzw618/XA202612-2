"""
sparse.build_sparse_vector 单元测试。

断言分词规则、FNV-1a hash、归一化权重与 C 侧（mock/真实桥接层）一致。
"""

from memoryhub.storage.vector_engine.sparse import _fnv1a32, build_sparse_vector


def test_fnv1a32_known_vectors():
    """与 FNV-1a 32-bit 标准测试向量对拍。"""
    assert _fnv1a32(b"") == 2166136261
    assert _fnv1a32(b"a") == 0xE40C292C
    assert _fnv1a32(b"foobar") == 0xBF9CF968


def test_ascii_tokenization():
    """ASCII 字母/数字连写为一个 token。"""
    terms = build_sparse_vector("hello world123")
    indices = [index for index, _ in terms]
    assert sorted(indices) == sorted([_fnv1a32(b"hello"), _fnv1a32(b"world123")])
    # 两个 token 等权重：1/2
    assert all(abs(weight - 0.5) < 1e-9 for _, weight in terms)


def test_ascii_case_sensitive():
    """ASCII token 保留大小写（与 C 侧逐位一致，C 不做小写转换）。"""
    lower = build_sparse_vector("python")
    upper = build_sparse_vector("Python")
    assert [i for i, _ in lower] == [_fnv1a32(b"python")]
    assert [i for i, _ in upper] == [_fnv1a32(b"Python")]
    assert lower[0][0] != upper[0][0]


def test_chinese_single_char_tokens():
    """中文等非 ASCII 字符逐字切分。"""
    terms = build_sparse_vector("编程语言")
    indices = [index for index, _ in terms]
    expected = sorted(_fnv1a32(ch.encode("utf-8")) for ch in "编程语言")
    assert sorted(indices) == expected
    assert all(abs(weight - 0.25) < 1e-9 for _, weight in terms)


def test_mixed_text_and_delimiters():
    """空白和标点仅作分隔，混合文本切分正确。"""
    terms = build_sparse_vector("Python 编程, 很好!")
    indices = sorted(index for index, _ in terms)
    expected = sorted(
        [_fnv1a32(b"Python")]
        + [_fnv1a32(ch.encode("utf-8")) for ch in "编程很好"]
    )
    assert indices == expected


def test_tf_normalization_and_dedup():
    """权重 = 出现次数 / 总 token 数，同索引计数累加。"""
    terms = dict(build_sparse_vector("go go go stop"))
    assert len(terms) == 2
    assert abs(terms[_fnv1a32(b"go")] - 0.75) < 1e-9
    assert abs(terms[_fnv1a32(b"stop")] - 0.25) < 1e-9


def test_deterministic_and_sorted():
    """同文本结果确定，且按索引升序。"""
    text = "MemoryHub 向量检索 测试"
    first = build_sparse_vector(text)
    second = build_sparse_vector(text)
    assert first == second
    indices = [index for index, _ in first]
    assert indices == sorted(indices)


def test_empty_text():
    """空文本 / 纯分隔符返回空列表。"""
    assert build_sparse_vector("") == []
    assert build_sparse_vector("  ,! \t\n") == []
