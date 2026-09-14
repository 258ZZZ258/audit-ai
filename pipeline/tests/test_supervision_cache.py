from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from test_supervision_extraction import Extractor, make_ir, request_data

from common.supervision import SupervisionExtractRequest
from pipeline.index.embedding_client import Embedding
from pipeline.supervision import prompting
from pipeline.supervision.cache import ResultCache
from pipeline.supervision.service import SupervisionConfig, SupervisionNotReady, SupervisionService
from pipeline.supervision.similarity import CachedEmbeddings, SimilarityRequest, score_pairs


def test_status_policy_change_invalidates_cached_extraction(monkeypatch, tmp_path):
    root = Path(prompting.__file__).parent
    for name in ("extraction-prompt.txt", "coverage-prompt.txt", "status-policy.txt"):
        (tmp_path / name).write_text((root / name).read_text("utf-8"), encoding="utf-8")
    monkeypatch.setattr(prompting, "__file__", str(tmp_path / "prompting.py"))
    client = Extractor()
    service = SupervisionService(None, None, SupervisionConfig(
        backend="gateway", max_evidence_chars=16000,
    ), client)
    monkeypatch.setattr(service, "_read_version", lambda request: (make_ir(), [["chunk", "text"]]))
    request = SupervisionExtractRequest.model_validate(request_data())
    service.extract(request)
    service.extract(request)
    assert len(client.inputs) == 1
    with (tmp_path / "status-policy.txt").open("a", encoding="utf-8") as stream:
        stream.write("\nAdditional status constraint")
    service.extract(request)
    assert len(client.inputs) == 2


def test_different_cache_keys_do_not_block_each_other():
    cache = ResultCache()
    entered = Event()
    release = Event()

    def slow():
        entered.set()
        assert release.wait(5)
        return 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.compute, "slow", slow)
        assert entered.wait(5)
        try:
            other = pool.submit(cache.compute, "fast", lambda: 2)
            assert other.result(timeout=2) == 2
            same = pool.submit(cache.compute, "slow", lambda: 99)
        finally:
            release.set()
        assert first.result() == 1
        assert same.result() == 1


def test_extraction_cache_revalidates_version_and_invalidates_metadata(monkeypatch):
    client = Extractor()
    service = SupervisionService(None, None, SupervisionConfig(
        backend="gateway", max_evidence_chars=16000,
    ), client)
    reads = []

    def read(request):
        reads.append(1)
        return make_ir(), [["chunk", "original"]]

    monkeypatch.setattr(service, "_read_version", read)
    request = SupervisionExtractRequest.model_validate(request_data())
    first = service.extract(request)
    first["facts"].clear()
    assert len(service.extract(request)["facts"]) == 1
    assert len(client.inputs) == 1
    assert len(reads) == 4
    request.metadata.title = "新标题"
    service.extract(request)
    assert len(client.inputs) == 2

    def unavailable(request):
        raise SupervisionNotReady("disabled")

    monkeypatch.setattr(service, "_read_version", unavailable)
    with pytest.raises(SupervisionNotReady):
        service.extract(request)


def test_cache_eviction_expiry_copy_and_failure(monkeypatch):
    clock = [0]
    monkeypatch.setattr("pipeline.supervision.cache.monotonic", lambda: clock[0])
    cache = ResultCache(1, 10)
    calls = []

    def compute():
        calls.append(1)
        return {"items": [1]}

    cache.compute("a", compute)["items"].append(2)
    assert cache.compute("a", compute) == {"items": [1]}
    assert len(calls) == 1
    clock[0] = 11
    cache.compute("a", compute)
    cache.compute("b", compute)
    cache.compute("a", compute)
    assert len(calls) == 4
    with pytest.raises(ValueError):
        cache.compute("bad", lambda: int("invalid"))
    assert cache.compute("bad", lambda: 42) == 42


def test_vectors_reused_across_pair_batches_without_score_changes():
    class Client:
        calls = []

        def embed(self, texts):
            self.calls.append(texts)
            return [Embedding([1, 0] if text != "合同" else [0, 1], {}) for text in texts]

    client = Client()
    cached = CachedEmbeddings(client)
    for record in ["整改", "合同", "整改"]:
        request = SimilarityRequest(pairs=[dict(pairId="p", issueText="设备", recordText=record)])
        assert score_pairs(request, cached)["scores"][0]["score"] == (0 if record == "合同" else 1)
    assert client.calls == [["设备", "整改"], ["合同"]]


def test_invalid_batch_not_cached():
    class Client:
        valid = False
        calls = 0

        def embed(self, texts):
            self.calls += 1
            return [Embedding([1, 0] if self.valid else [float("nan"), 0], {}) for _ in texts]

    client = Client()
    cached = CachedEmbeddings(client)
    with pytest.raises(ValueError):
        cached.embed(["文本"])
    client.valid = True
    assert cached.embed(["文本"])[0].dense == [1, 0]
    assert client.calls == 2
