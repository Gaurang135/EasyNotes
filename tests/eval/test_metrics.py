from tests.eval.metrics import recall_at_k, mrr


def test_recall_at_k():
    assert recall_at_k([1, 2, 3], {2}, 10) == 1.0
    assert recall_at_k([1, 2, 3], {9}, 10) == 0.0
    assert recall_at_k([1, 2, 3, 4], {3, 9}, 2) == 0.0
    assert recall_at_k([3, 1], {3, 9}, 2) == 0.5


def test_mrr():
    assert mrr([1, 2, 3], {2}) == 0.5
    assert mrr([1, 2, 3], {9}) == 0.0
