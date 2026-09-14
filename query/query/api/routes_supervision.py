"""Java 内部监督字段提取；服务令牌鉴权，用户权限已由 Java 计算。"""

import hashlib
import os
import tomllib
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from common.supervision import SupervisionExtractRequest
from pipeline.config import DEFAULT_CONFIG_DIR, load_config
from pipeline.index.embedding_client import EmbeddingClient
from pipeline.llm_client import LLMError, make_llm_client
from pipeline.supervision import verification
from pipeline.supervision.association import AssociationRequest, judge_pairs
from pipeline.supervision.cache import ResultCache
from pipeline.supervision.service import (
    SupervisionConfig,
    SupervisionNotReady,
    SupervisionService,
    SupervisionVersionNotFound,
)
from pipeline.supervision.similarity import CachedEmbeddings, SimilarityRequest, score_pairs
from pipeline.supervision.verification import VerificationRequest, verify_claims
from query.api.auth import require_internal_token
from query.api.errors import ApiError, not_found, validation_error

router = APIRouter(tags=["supervision"], dependencies=[Depends(require_internal_token)])


def _run_model_operation(body, request, operation, prompt_name):
    injected = getattr(request.app.state, "supervision_association_client", None)
    if injected is not None:
        return operation(body, injected)
    path = Path(os.environ.get("SUPERVISION_CONFIG", str(DEFAULT_CONFIG_DIR / "supervision.toml")))
    config = SupervisionConfig.model_validate(tomllib.loads(path.read_text("utf-8")))
    if config.backend != "gateway":
        raise ApiError(503, "SUPERVISION_MODEL_DISABLED", "监督模型尚未启用")
    client = make_llm_client(timeout=config.model_timeout_seconds, retries=1)
    cache = getattr(request.app.state, "supervision_result_cache", None)
    settings = (config.cache_entries, config.cache_ttl_seconds)
    if cache is None or getattr(request.app.state, "supervision_cache_settings", None) != settings:
        cache = ResultCache(*settings)
        request.app.state.supervision_result_cache = cache
        request.app.state.supervision_cache_settings = settings
    # Read the installed module resource, independent of worktree/package layout.
    prompt = Path(verification.__file__).with_name(prompt_name)
    key = hashlib.sha256("\0".join([
        operation.__name__, body.model_dump_json(), prompt.read_text("utf-8"),
        os.environ.get("OPENAI_BASE_URL", ""), client.model,
        os.environ.get("OPENAI_API_KEY", ""), config.model_dump_json(),
    ]).encode()).hexdigest()

    def run():
        for attempt in range(config.model_attempts):
            try:
                return operation(body, client)
            except LLMError:
                if attempt + 1 == config.model_attempts:
                    raise
        raise RuntimeError("No model attempt")

    return cache.compute(key, run)


@router.post("/v1/supervision/verify-fields")
def supervision_verify_fields(body: VerificationRequest, request: Request):
    try:
        return _run_model_operation(body, request, verify_claims, "verification-prompt.txt")
    except LLMError as exc:
        raise ApiError(502, "SUPERVISION_MODEL_FAILED", "监督字段核验失败") from exc
    except ValueError as exc:
        raise validation_error("监督字段核验响应不完整或无效") from exc


@router.post("/v1/supervision/associate")
def supervision_associate(body: AssociationRequest, request: Request):
    try:
        return _run_model_operation(body, request, judge_pairs, "association-prompt.txt")
    except LLMError as exc:
        raise ApiError(502, "SUPERVISION_MODEL_FAILED", "监督关联模型调用失败") from exc
    except ValueError as exc:
        raise validation_error("监督关联结果校验失败") from exc


@router.post("/v1/supervision/similarity")
def supervision_similarity(body: SimilarityRequest, request: Request):
    client = getattr(request.app.state, "supervision_embedding_client", None)
    if client is None:
        path = Path(os.environ.get(
            "SUPERVISION_CONFIG", str(DEFAULT_CONFIG_DIR / "supervision.toml")
        ))
        config = SupervisionConfig.model_validate(tomllib.loads(path.read_text("utf-8")))
        client = CachedEmbeddings(EmbeddingClient.from_config(load_config()),
                                  config.embedding_cache_entries, config.cache_ttl_seconds)
        request.app.state.supervision_embedding_client = client
    try:
        return score_pairs(body, client)
    except ValueError as exc:
        raise validation_error("监督关联向量计算校验失败") from exc


def get_supervision_service(request: Request) -> SupervisionService:
    svc = getattr(request.app.state, "supervision_service", None)
    if svc is None:
        svc = SupervisionService.from_config()
        request.app.state.supervision_service = svc
    return svc


@router.post("/v1/supervision/extract")
def extract_supervision(
    body: SupervisionExtractRequest,
    svc: SupervisionService = Depends(get_supervision_service),
):
    try:
        return svc.extract(body)
    except SupervisionVersionNotFound as exc:
        raise not_found("文档版本不存在") from exc
    except SupervisionNotReady as exc:
        raise ApiError(409, "SUPERVISION_NOT_READY", str(exc)) from exc
    except FileNotFoundError as exc:
        raise ApiError(409, "SUPERVISION_NOT_READY", "文档解析产物缺失") from exc
    except ValueError as exc:
        # 模型原始输出/验证错误可能含正文，不回传异常细节。
        raise validation_error("监督提取结果或解析数据校验失败") from exc
