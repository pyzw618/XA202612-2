"""
冲突处理评测模块

评测冲突检测和解决的正确率。
"""

from memoryhub.adapter.schemas import EvalReport


class ConflictEvaluator:
    """
    冲突处理评测器

    使用方式:
        evaluator = ConflictEvaluator(detector, resolver)
        report = evaluator.run("evaluation/datasets/conflict_test.json")
    """

    def __init__(self, conflict_detector=None, conflict_resolver=None):
        self.detector = conflict_detector
        self.resolver = conflict_resolver

    def run(self, dataset_path: str) -> EvalReport:
        """
        运行冲突处理评测

        数据流:
            加载测试数据集 → 逐条检测冲突 → 解决冲突 → 与标注对比

        参数:
            dataset_path: 测试数据集路径

        返回:
            EvalReport

        测试数据集格式:
            [
                {
                    "sample_id": "s001",
                    "old_preference": "项目周报默认使用 Markdown",
                    "new_preference": "以后周报改成 Word",
                    "expected_decision": "override",
                    "scene": "office"
                },
                ...
            ]
        """
        raise NotImplementedError

    def evaluate_detection(self, dataset_path: str) -> dict:
        """
        评测冲突检测准确率

        返回:
            {"detection_accuracy": float, "false_positive_rate": float}
        """
        raise NotImplementedError

    def evaluate_resolution(self, dataset_path: str) -> dict:
        """
        评测冲突解决正确率

        返回:
            {"resolution_accuracy": float}
        """
        raise NotImplementedError
