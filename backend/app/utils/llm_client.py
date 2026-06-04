"""
LLM Client Wrapper
Unified OpenAI format API calls
Supports Ollama num_ctx parameter to prevent prompt truncation
"""

import json
import os
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config


class LLMClient:
    """LLM Client"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
        )

        # Ollama context window size — prevents prompt truncation.
        # Read from env OLLAMA_NUM_CTX, default 8192 (Ollama default is only 2048).
        self._num_ctx = int(os.environ.get('OLLAMA_NUM_CTX', '8192'))

    def _is_ollama(self) -> bool:
        """Check if we're talking to an Ollama server."""
        return '11434' in (self.base_url or '')

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        """
        Send chat request

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Max token count
            response_format: Response format (e.g., JSON mode)

        Returns:
            Model response text
        """
        kwargs = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        # For Ollama: pass num_ctx via extra_body to prevent prompt truncation
        if self._is_ollama() and self._num_ctx:
            kwargs["extra_body"] = {
                "options": {"num_ctx": self._num_ctx}
            }

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # Some models (like MiniMax M2.5) include <think>thinking content in response, need to remove
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def model_for_task(self, task: str) -> str:
        """Return the configured model alias for a smoke task."""
        aliases = {
            "json": Config.MIROFISH_JSON_MODEL,
            "ner": Config.MIROFISH_NER_MODEL,
            "report": Config.MIROFISH_REPORT_MODEL,
            "repair": Config.MIROFISH_REPAIR_MODEL,
        }
        return aliases.get(task, None) or self.model

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send chat request and return JSON

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Max token count

        Returns:
            Parsed JSON object
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            model=model,
            reasoning_effort=reasoning_effort,
        )
        # Clean markdown code block markers
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return self._parse_json_response(cleaned_response)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON format from LLM "
                f"(chars={len(cleaned_response)}, error={exc.msg})"
            ) from exc

    def chat_schema(
        self,
        task: str,
        schema: Dict[str, Any],
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Request JSON matching a schema and validate it without leaking raw output."""
        model = self.model_for_task(task)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": f"mirofish_{re.sub(r'[^a-zA-Z0-9_]+', '_', task)}",
                "strict": True,
                "schema": schema,
            },
        }
        try:
            response = self.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            parsed = self._parse_json_response(response.strip())
        except Exception as exc:
            if not self._looks_like_unsupported_schema(exc):
                raise self._schema_error(task, model, "$", type(exc).__name__) from exc
            parsed = self._chat_schema_fallback(
                schema=schema,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                reasoning_effort=reasoning_effort,
            )

        validation_error = validate_json_schema(parsed, schema)
        if validation_error:
            parsed = self._chat_schema_fallback(
                schema=schema,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            validation_error = validate_json_schema(parsed, schema)
            if validation_error:
                path, message = validation_error
                raise self._schema_error(task, model, path, message)
        return parsed

    def _chat_schema_fallback(
        self,
        schema: Dict[str, Any],
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        fallback_messages = [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON matching this JSON Schema. "
                    "Do not use markdown or explanatory text.\n"
                    f"{json.dumps(schema, ensure_ascii=False)}"
                ),
            },
            *messages,
        ]
        return self.chat_json(
            messages=fallback_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    @staticmethod
    def _parse_json_response(cleaned_response: str) -> Dict[str, Any]:
        """Parse a JSON object from model output without exposing raw content on failure."""
        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            start = cleaned_response.find("{")
            if start < 0:
                raise

            decoder = json.JSONDecoder()
            parsed, _ = decoder.raw_decode(cleaned_response[start:])
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError(
                    "top-level JSON value is not an object",
                    cleaned_response,
                    start,
                )
            return parsed

    @staticmethod
    def _looks_like_unsupported_schema(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "response_format" in text
            or "json_schema" in text
            or "unsupported" in text
            or "not support" in text
        )

    @staticmethod
    def _schema_error(task: str, model: str, path: str, message: str) -> ValueError:
        return ValueError(
            f"Schema validation failed for task={task!r}, model={model!r}, "
            f"path={path}, error={message}"
        )


def validate_json_schema(value: Any, schema: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """Validate the small JSON Schema subset used by smoke tests."""

    def validate(current: Any, current_schema: Dict[str, Any], path: str) -> Optional[tuple[str, str]]:
        schema_type = current_schema.get("type")
        if schema_type == "object":
            if not isinstance(current, dict):
                return path, "expected object"
            for key in current_schema.get("required", []):
                if key not in current:
                    return f"{path}.{key}", "required property missing"
            properties = current_schema.get("properties", {})
            for key, child_schema in properties.items():
                if key in current:
                    error = validate(current[key], child_schema, f"{path}.{key}")
                    if error:
                        return error
        elif schema_type == "array":
            if not isinstance(current, list):
                return path, "expected array"
            min_items = current_schema.get("minItems")
            max_items = current_schema.get("maxItems")
            if min_items is not None and len(current) < min_items:
                return path, f"expected at least {min_items} items"
            if max_items is not None and len(current) > max_items:
                return path, f"expected at most {max_items} items"
            item_schema = current_schema.get("items")
            if item_schema:
                for index, item in enumerate(current):
                    error = validate(item, item_schema, f"{path}[{index}]")
                    if error:
                        return error
        elif schema_type == "string":
            if not isinstance(current, str):
                return path, "expected string"
            min_length = current_schema.get("minLength")
            if min_length is not None and len(current.strip()) < min_length:
                return path, f"expected string length at least {min_length}"
            enum = current_schema.get("enum")
            if enum and current not in enum:
                return path, "unexpected enum value"
        elif schema_type == "integer":
            if not isinstance(current, int) or isinstance(current, bool):
                return path, "expected integer"
        elif schema_type == "number":
            if not isinstance(current, (int, float)) or isinstance(current, bool):
                return path, "expected number"
        elif schema_type == "boolean":
            if not isinstance(current, bool):
                return path, "expected boolean"
        return None

    return validate(value, schema, "$")
