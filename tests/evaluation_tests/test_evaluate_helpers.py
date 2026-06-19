from evaluation.evaluate import normalize_so_hieu_for_evaluation


def test_normalize_qh_term_typo_for_current_benchmark_grouping():
    assert normalize_so_hieu_for_evaluation("59/2024/QH25") == "59/2024/QH15"


def test_normalize_qh_term_keeps_valid_so_hieu():
    assert normalize_so_hieu_for_evaluation("59/2024/QH15") == "59/2024/QH15"
