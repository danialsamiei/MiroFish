"""
LLM Client wrapper
Unified OpenAI-compatible format for all LLM calls.
Handles Claude, GPT, Qwen, and other models through LiteLLM gateway.
"""

import json
import re
import time
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config
from .logger import get_logger

logger = get_logger('mirofish.llm_client')


class LLMClient:
    """LLM Client with retry and Claude compatibility."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=900.0,
            max_retries=3,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        Send a chat completion request.

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Maximum tokens
            response_format: Response format (e.g. JSON mode)

        Returns:
            Model response text
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        # Add extra headers for LiteLLM to set longer timeout
        extra_headers = {"x-litellm-timeout": "600"}
        kwargs["extra_headers"] = extra_headers

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if content is None:
            content = ''
        # Some models include <think> blocks in content
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Send a chat request and return parsed JSON.
        Retries on empty responses or parse failures.

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Maximum tokens
            max_retries: Maximum retry attempts

        Returns:
            Parsed JSON object
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                # Don't use response_format - Claude doesn't support it via LiteLLM
                response = self.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if not response:
                    logger.warning(f"Empty LLM response (attempt {attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise ValueError("LLM returned empty response after retries")

                # Clean markdown code block markers
                cleaned = response.strip()
                cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\n?```\s*$', '', cleaned)
                cleaned = cleaned.strip()

                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    # Try json-repair as last resort
                    try:
                        from json_repair import repair_json
                        repaired = repair_json(cleaned, return_objects=True)
                        if isinstance(repaired, dict):
                            return repaired
                    except Exception:
                        pass

                    last_error = f"Invalid JSON: {cleaned[:200]}"
                    logger.warning(f"JSON parse failed (attempt {attempt+1}): {last_error}")
                    if attempt < max_retries - 1:
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise ValueError(f"LLM returned invalid JSON after {max_retries} attempts: {cleaned[:200]}")

            except ValueError:
                raise
            except Exception as e:
                last_error = str(e)
                logger.warning(f"LLM call failed (attempt {attempt+1}): {last_error}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

        raise ValueError(f"LLM failed after {max_retries} retries: {last_error}")
