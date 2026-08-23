from app.search.embeddings import FakeEmbedder


def test_fake_is_deterministic_and_right_dim():
    e = FakeEmbedder(dim=8)
    v1 = e.embed_passages(["hello"])[0]
    v2 = e.embed_passages(["hello"])[0]
    assert v1 == v2
    assert len(v1) == 8


def test_query_differs_from_passage_for_same_text():
    e = FakeEmbedder(dim=8)
    q = e.embed_query("hello")
    p = e.embed_passages(["hello"])[0]
    assert q != p  # the query instruction must change the vector
