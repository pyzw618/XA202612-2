"""
知识检索评测模块

评测检索的召回率、MRR、NDCG 等指标。
"""

from memoryhub.adapter.schemas import EvalReport


class RetrievalEvaluator:
    """
    知识检索评测器

    使用方式:
        evaluator = RetrievalEvaluator(retriever)
        report = evaluator.run("evaluation/datasets/retrieval_test.json")
    """

    def __init__(self, retriever=None):
        """
        参数:
            retriever: HybridRetriever 实例
        """
        self.retriever = retriever

    def run(self, dataset_path: str) -> EvalReport:
        """
        运行检索评测

        数据流:
            加载测试数据集 → 逐条检索 → 与标注对比 → 计算指标

        参数:
            dataset_path: 测试数据集路径

        返回:
            EvalReport

        测试数据集格式:
            [
                {
                    "sample_id": "s001",
                    "query": "按上次的方式生成周报",
                    "expected_ids": ["know_001", "pref_003"],
                    "scene": "office"
                },
                ...
            ]
        """
        raise NotImplementedError

    def recall_at_k(self, expected_ids: list[str], retrieved_ids: list[str], k: int) -> float:
        """
        计算 Recall@K

        参数:
            expected_ids: 期望检索到的记忆 ID 列表
            retrieved_ids: 实际检索到的记忆 ID 列表
            k: 截断位置

        返回:
            Recall@K 值
        """
        raise NotImplementedError

    def mrr(self, expected_ids: list[str], retrieved_ids: list[str]) -> float:
        """
        计算 MRR (Mean Reciprocal Rank)

        返回:
            MRR 值
        """
        raise NotImplementedError

    def ndcg(self, expected_ids: list[str], retrieved_ids: list[str], k: int) -> float:
        """
        计算 NDCG@K (Normalized Discounted Cumulative Gain)

        返回:
            NDCG@K 值
        """
        raise NotImplementedError
