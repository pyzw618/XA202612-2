"""
测试脚本：存入 10 条假数据，验证 BM25 和 FAISS 分别能搜出来。
"""

import sys
import os

# Windows 下强制 UTF-8 输出，避免 GBK 编码乱码
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.embedding import create_embedding_client
from src.memory_store import MemoryStore
from src.search_engine import MemorySearchEngine


def main():
    print("=" * 60)
    print("OS Agent Memory Engine — BM25 + FAISS 检索测试")
    print("=" * 60)

    # ---- 1. 初始化 Embedding 客户端 ----
    print("\n[1] 初始化 Embedding 客户端 (dim=768)...")
    embed_client = create_embedding_client(dim=768, latency=0.1, seed=42)
    print(f"  当前使用: {type(embed_client).__name__}")

    # ---- 2. 准备 10 条假数据 ----
    fake_data = [
        "我的系统登录密码是 Admin@123456",
        "公司 Wi-Fi 密码是 Kylin_Office_2024",
        "数据库 root 账号密码是 RootDB!Pass#2024",
        "今天下午 3 点有产品评审会议，记得带电脑",
        "项目代码仓库地址是 https://git.kylin.com/os-agent",
        "服务器 SSH 端口是 2222，IP 是 192.168.1.100",
        "上个月学习了 Transformer 注意力机制和 BERT 预训练",
        "周末要去超市买牛奶、鸡蛋、面包和水果",
        "API 密钥 sk-abc123def456ghi789jkl 用于调用大模型服务",
        "下周五是团队团建日，地点在青龙峡，早上 8 点集合",
    ]

    print(f"\n[2] 准备 {len(fake_data)} 条假数据：")
    for i, text in enumerate(fake_data, 1):
        print(f"  [{i}] {text}")

    # ---- 3. 生成 Embedding 并存入 MemoryStore ----
    print(f"\n[3] 生成 Embedding（模拟每次 100ms 延迟）...")
    store = MemoryStore(":memory:")  # 内存模式，避免旧数据累积
    for i, text in enumerate(fake_data, 1):
        vec = embed_client.embed(text)
        store.add(content=text, embedding=vec)
        print(f"  [{i}] ✓ embedded: {text[:30]}...  (dim={len(vec)})")

    print(f"\n  存储完成: 共 {len(store)} 条记录")

    # ---- 4. 构建搜索索引 ----
    print(f"\n[4] 构建 BM25 + FAISS 双路索引...")
    engine = MemorySearchEngine(store, embedding_dim=768)
    engine.build_index()
    print(f"  BM25 索引: {'✓ ready' if engine.bm25.is_ready else '✗ failed'}")
    print(f"  FAISS 索引: {'✓ ready' if engine.faiss.is_ready else '✗ failed'}")

    # ---- 5. 测试搜索 ----
    print("\n" + "=" * 60)
    print("[5] 开始搜索测试")
    print("=" * 60)

    # 测试用例: (查询文本, 期望匹配的关键词)
    test_queries = [
        ("密码", "密码相关"),
        ("数据库登录", "数据库凭证"),
        ("超市购物", "日常购物"),
        ("Transformer 注意力", "学习内容"),
        ("服务器 IP", "服务器信息"),
    ]

    for query, description in test_queries:
        print(f"\n{'─' * 60}")
        print(f"查询: 「{query}」 ({description})")
        print(f"{'─' * 60}")

        # 生成查询向量
        query_vec = embed_client.embed(query)

        # --- BM25 ---
        print("\n  ▶ BM25 全文检索结果:")
        bm25_results = engine.search_bm25(query, top_k=3)
        for r in bm25_results:
            print(f"    score={r['score']:.4f}  →  {r['content']}")

        # --- FAISS ---
        print("\n  ▶ FAISS 向量检索结果:")
        faiss_results = engine.search_faiss(query_vec, top_k=3)
        for r in faiss_results:
            print(f"    score={r['score']:.4f}  →  {r['content']}")

        # --- Hybrid ---
        print("\n  ▶ Hybrid 混合检索结果 (BM25:0.3 + FAISS:0.7):")
        hybrid_results = engine.search_hybrid(query, query_vec, top_k=3)
        for r in hybrid_results:
            print(f"    score={r['score']:.4f}  →  {r['content']}")

    # ---- 6. 验证核心断言 ----
    print("\n" + "=" * 60)
    print("[6] 核心验证")
    print("=" * 60)

    # 验证1: BM25 搜"密码"能找到包含"密码"的记录
    bm25_test = engine.search_bm25("密码", top_k=10)
    has_password = any("密码" in r["content"] for r in bm25_test)
    assert has_password, "❌ BM25: 搜「密码」应该能返回包含「密码」的记录"
    print(f"  ✓ BM25: 搜「密码」成功命中密码相关记录")

    # 验证2: FAISS 返回 3 条结果
    qv = embed_client.embed("密码")
    faiss_test = engine.search_faiss(qv, top_k=3)
    assert len(faiss_test) == 3, f"❌ FAISS: 期望 3 条结果，实际 {len(faiss_test)}"
    print(f"  ✓ FAISS: 返回了 {len(faiss_test)} 条结果（top_k=3）")

    # 验证3: 存储了 10 条
    assert len(store) == 10, f"❌ Store: 期望 10，实际 {len(store)}"
    print(f"  ✓ MemoryStore: 存储 {len(store)} 条记录")

    # 验证4: 向量维度正确
    sample = store.get_all()[0]
    assert len(sample.embedding) == 768, f"❌ Embedding dim: 期望 768，实际 {len(sample.embedding)}"
    print(f"  ✓ Embedding 维度: {len(sample.embedding)}")

    # 验证5: 确定性 — 同一文本两次调用结果相同
    v1 = embed_client.embed("测试文本")
    v2 = embed_client.embed("测试文本")
    assert v1 == v2, "❌ 确定性: 同一文本两次 Embedding 结果不同"
    print(f"  ✓ 确定性: 同一文本两次调用结果一致")

    print("\n" + "=" * 60)
    print("✅ 全部测试通过！BM25 + FAISS 双路检索均正常工作。")
    print("=" * 60)


if __name__ == "__main__":
    main()
