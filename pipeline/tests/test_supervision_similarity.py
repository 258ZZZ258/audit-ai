import pytest

from pipeline.index.embedding_client import Embedding
from pipeline.supervision.similarity import SimilarityRequest, score_pairs


def test_pair_specific_cosine_and_deduplicated_embedding():
    class Client:
        def embed(self, texts):
            assert texts == ['设备问题', '设备整改', '合同整改']
            return [Embedding([1, 0], {}), Embedding([2, 0], {}), Embedding([0, 1], {})]

    request = SimilarityRequest(pairs=[
        dict(pairId='a', issueText='设备问题', recordText='设备整改'),
        dict(pairId='b', issueText='设备问题', recordText='合同整改'),
    ])
    assert score_pairs(request, Client()) == {'scores': [
        {'pairId': 'a', 'score': 1}, {'pairId': 'b', 'score': 0},
    ]}


@pytest.mark.parametrize('vector', [[], [float('nan')], [0, 0]])
def test_invalid_vectors_fail(vector):
    class Client:
        def embed(self, texts):
            return [Embedding(vector, {}) for _ in texts]

    with pytest.raises(ValueError):
        request = SimilarityRequest(pairs=[dict(pairId='a', issueText='甲', recordText='乙')])
        score_pairs(request, Client())
