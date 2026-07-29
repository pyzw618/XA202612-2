"""
偏好提取评测模块

评测偏好提取的准确率、精确率、召回率、F1。
"""

from memoryhub.adapter.schemas import EvalSample, EvalResult, EvalReport


class PreferenceEvaluator:
    """
    偏好提取评测器

    使用方式:
        evaluator = PreferenceEvaluator(extractor)
        report = evaluator.run("evaluation/datasets/preference_test.json")
    """

    def __init__(self, preference_extractor=None):
        """
        参数:
            preference_extractor: PreferenceExtractor 实例
        """
        self.extractor = preference_extractor

    def run(self, dataset_path: str) -> EvalReport:
        """
        运行偏好提取评测

        数据流:
            加载测试数据集 → 逐条提取偏好 → 与标注对比 → 计算指标

        参数:
            dataset_path: 测试数据集路径（JSON 格式）

        返回:
            EvalReport

        测试数据集格式:
            [
                {
                    "sample_id": "s001",
                    "input_text": "以后都用 Markdown 写周报",
                    "expected_output": "项目周报默认使用 Markdown",
                    "expected_type": "format_preference"
                },
                ...
            ]
        """
        raise NotImplementedError

    def evaluate_single(self, sample: EvalSample) -> EvalResult:
        """
        评测单条样本

        参数:
            sample: 评测样本

        返回:
            EvalResult
        """
        raise NotImplementedError

    def compute_metrics(self, results: list[EvalResult]) -> dict:
        """
        计算汇总指标

        返回:
            {
                "accuracy": float,
                "precision": float,
                "recall": float,
                "f1": float,
                "avg_latency_ms": float
            }
        """
        raise NotImplementedError
