from app.search.rrf import rrf


def test_rrf_rewards_agreement():
    # chunk 2 appears high in both lists -> should win
    fused = rrf([[1, 2, 3], [2, 4, 5]], k=60)
    assert fused[0][0] == 2
    ids = [c for c, _ in fused]
    assert set(ids) == {1, 2, 3, 4, 5}


def test_rrf_empty():
    assert rrf([[], []]) == []
