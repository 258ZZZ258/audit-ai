from fastapi.testclient import TestClient

from pipeline.index.embedding_client import Embedding
from query.api.app import create_app


def test_similarity_auth_and_pair_results(monkeypatch):
    monkeypatch.setenv('AUDIT_AI_INTERNAL_TOKEN', 'test')
    app = create_app()

    class Client:
        calls = 0

        def embed(self, texts):
            self.calls += 1
            return [Embedding([1, 0], {}) for _ in texts]

    client = Client()
    app.state.supervision_embedding_client = client
    http = TestClient(app)
    body = {'pairs': [{'pairId': 'a', 'issueText': '设备问题', 'recordText': '设备整改'}]}
    assert http.post('/v1/supervision/similarity', json=body).status_code == 401
    assert client.calls == 0
    result = http.post('/v1/supervision/similarity', json=body,
                       headers={'X-Internal-Token': 'test'})
    assert result.status_code == 200
    assert result.json() == {'scores': [{'pairId': 'a', 'score': 1}]}
    body['pairs'].append(body['pairs'][0])
    assert http.post('/v1/supervision/similarity', json=body,
                     headers={'X-Internal-Token': 'test'}).status_code == 422
    assert client.calls == 1
