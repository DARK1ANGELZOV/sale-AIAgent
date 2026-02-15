"""LLM abstractions for API and local inference backends."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from abc import ABC, abstractmethod

from app.core.constants import REFUSAL_TEXT
from app.core.exceptions import EmptyLLMResponseError, LLMTimeoutError, ModelMemoryError
from app.core.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.models.schemas import AnswerMode, LLMResult, QueryType


class BaseLLMClient(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def generate(
        self,
        question: str,
        query_type: QueryType,
        context: str,
        question_profile: str,
        response_mode: AnswerMode,
    ) -> LLMResult:
        """Generate answer from question + context."""


class OpenAIClient(BaseLLMClient):
    """OpenAI API-based client."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        timeout_sec: int,
        temperature: float,
        max_tokens: int,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_sec = timeout_sec
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._base_url = base_url
        self._client = None
        self._lock = threading.Lock()

    def _lazy_load_client(self) -> None:
        if self._client is not None:
            return
        with self._lock:
            if self._client is not None:
                return
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)

    async def generate(
        self,
        question: str,
        query_type: QueryType,
        context: str,
        question_profile: str,
        response_mode: AnswerMode,
    ) -> LLMResult:
        self._lazy_load_client()
        user_prompt = USER_PROMPT_TEMPLATE.format(
            query_type=query_type.value,
            response_mode=response_mode.value,
            mode_instruction=_mode_instruction(response_mode),
            question_profile=question_profile,
            question=question,
            context=context,
        )

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(  # type: ignore[union-attr]
                    model=self._model_name,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT.strip()},
                        {"role": "user", "content": user_prompt.strip()},
                    ],
                ),
                timeout=self._timeout_sec,
            )
        except TimeoutError as exc:
            raise LLMTimeoutError("OpenAI request timeout") from exc
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError("OpenAI request timeout") from exc

        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise EmptyLLMResponseError("LLM returned empty content")

        usage = response.usage
        return LLMResult(
            answer=content,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


class LocalLlamaClient(BaseLLMClient):
    """llama.cpp local model backend."""

    def __init__(
        self,
        model_path: str,
        model_name: str,
        timeout_sec: int,
        temperature: float,
        max_tokens: int,
        context_size: int,
        threads: int,
        model_repo_id: str | None = None,
        model_filename: str | None = None,
    ) -> None:
        self._model_path = model_path
        self._model_name = model_name
        self._timeout_sec = timeout_sec
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._context_size = context_size
        self._threads = threads
        self._model_repo_id = model_repo_id
        self._model_filename = model_filename
        self._llm = None
        self._lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def _ensure_model_exists(self) -> str:
        model_path = Path(self._model_path)
        if model_path.exists():
            return str(model_path)

        if not self._model_repo_id or not self._model_filename:
            raise ModelMemoryError(
                "Local model file does not exist and no HuggingFace source is configured"
            )

        model_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from huggingface_hub import hf_hub_download

            downloaded_path = hf_hub_download(
                repo_id=self._model_repo_id,
                filename=self._model_filename,
                local_dir=str(model_path.parent),
                local_dir_use_symlinks=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise ModelMemoryError("Failed to download local model from HuggingFace") from exc

        self._model_path = downloaded_path
        return downloaded_path

    def _lazy_load_model(self) -> None:
        if self._llm is not None:
            return
        with self._lock:
            if self._llm is not None:
                return
            resolved_model_path = self._ensure_model_exists()
            try:
                from llama_cpp import Llama

                self._llm = Llama(
                    model_path=resolved_model_path,
                    n_ctx=self._context_size,
                    n_threads=self._threads,
                    verbose=False,
                )
            except MemoryError as exc:
                raise ModelMemoryError("Not enough memory for local LLM") from exc
            except Exception as exc:  # noqa: BLE001
                raise ModelMemoryError(
                    f"Failed to initialize local model: {self._model_path}"
                ) from exc

    async def generate(
        self,
        question: str,
        query_type: QueryType,
        context: str,
        question_profile: str,
        response_mode: AnswerMode,
    ) -> LLMResult:
        self._lazy_load_model()
        user_prompt = USER_PROMPT_TEMPLATE.format(
            query_type=query_type.value,
            response_mode=response_mode.value,
            mode_instruction=_mode_instruction(response_mode),
            question_profile=question_profile,
            question=question,
            context=context,
        )

        def _run_completion() -> dict:
            with self._inference_lock:
                return self._llm.create_chat_completion(  # type: ignore[union-attr]
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT.strip()},
                        {"role": "user", "content": user_prompt.strip()},
                    ],
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_run_completion),
                timeout=self._timeout_sec,
            )
        except TimeoutError as exc:
            raise LLMTimeoutError("Local LLM timeout") from exc
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError("Local LLM timeout") from exc
        except MemoryError as exc:
            raise ModelMemoryError("Memory overflow during local generation") from exc
        except OSError as exc:
            raise ModelMemoryError("Local LLM runtime error") from exc
        except Exception as exc:  # noqa: BLE001
            raise EmptyLLMResponseError("Local LLM generation failed") from exc

        content = str(response["choices"][0]["message"]["content"]).strip()
        if not content:
            raise EmptyLLMResponseError("Local LLM returned empty response")

        usage = response.get("usage", {}) or {}
        return LLMResult(
            answer=content,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )


class LLMService:
    """Factory wrapper that routes generation to selected provider."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        timeout_sec: int,
        temperature: float,
        max_tokens: int,
        api_key: str | None = None,
        base_url: str | None = None,
        local_model_path: str | None = None,
        local_model_repo_id: str | None = None,
        local_model_filename: str | None = None,
        local_context_size: int = 4096,
        local_threads: int = 8,
    ) -> None:
        if provider == "api":
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required when llm_provider=api")
            self._client: BaseLLMClient = OpenAIClient(
                api_key=api_key,
                model_name=model_name,
                timeout_sec=timeout_sec,
                temperature=temperature,
                max_tokens=max_tokens,
                base_url=base_url,
            )
        elif provider == "local":
            if not local_model_path:
                raise ValueError("LOCAL_MODEL_PATH is required when llm_provider=local")
            self._client = LocalLlamaClient(
                model_path=local_model_path,
                model_name=model_name,
                timeout_sec=timeout_sec,
                temperature=temperature,
                max_tokens=max_tokens,
                context_size=local_context_size,
                threads=local_threads,
                model_repo_id=local_model_repo_id,
                model_filename=local_model_filename,
            )
        else:
            raise ValueError("llm_provider must be one of: api, local")

    async def answer(
        self,
        question: str,
        query_type: QueryType,
        context: str,
        question_profile: str = "",
        response_mode: AnswerMode = AnswerMode.standard,
    ) -> LLMResult:
        """Generate answer or refusal when context is empty."""
        if not context.strip():
            return LLMResult(answer=REFUSAL_TEXT)
        return await self._client.generate(
            question=question,
            query_type=query_type,
            context=context,
            question_profile=question_profile,
            response_mode=response_mode,
        )


def _mode_instruction(mode: AnswerMode) -> str:
    if mode == AnswerMode.brief:
        return (
            "- Keep answer concise: 3-6 short sentences.\n"
            "- Focus on direct conclusion and one key evidence point."
        )
    if mode == AnswerMode.deep:
        return (
            "- Provide layered explanation: conclusion, mechanism, practical implications.\n"
            "- Add clear bullets and include edge cases from context when available."
        )
    return (
        "- Provide balanced answer with short structure: conclusion + explanation + practice.\n"
        "- Avoid unnecessary verbosity."
    )
