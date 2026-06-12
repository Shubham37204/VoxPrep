from __future__ import annotations

import time

import httpx

from app.config.settings import get_settings
from app.observability.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

# OpenAI TTS — high quality, low latency, works well for interview questions.
# Swap voice/model via settings without touching this service.
_TTS_URL = "https://api.openai.com/v1/audio/speech"
_DEFAULT_VOICE = "alloy"     # Neutral, clear — good for interview context
_DEFAULT_MODEL = "tts-1"     # tts-1-hd for higher quality at 2x latency


class TTSService:
    """
    Convert question text to MP3 audio bytes via OpenAI TTS.
    Returns raw audio bytes — API layer streams directly to client.

    WHY OpenAI TTS (not Groq):
      Groq has no TTS endpoint. ElevenLabs is higher quality but
      2-3x more expensive and adds a dependency. OpenAI TTS covers
      the interview use case cleanly at reasonable cost (~$15/1M chars).
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def synthesize(
        self,
        text: str,
        voice: str = _DEFAULT_VOICE,
        model: str = _DEFAULT_MODEL,
    ) -> tuple[bytes, int]:
        """
        Convert text to MP3 audio bytes.

        Args:
            text:  Text to synthesize. Keep under 4096 chars (OpenAI limit).
            voice: alloy | echo | fable | onyx | nova | shimmer
            model: tts-1 (fast) | tts-1-hd (quality)

        Returns:
            (audio_bytes, latency_ms)

        Raises:
            ValueError: Empty text.
            httpx.HTTPStatusError: API error — caller maps to 502.
        """
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        if len(text) > 4096:
            raise ValueError(f"text too long: {len(text)} chars exceeds OpenAI 4096 limit")

        t0 = time.monotonic()
        response = await self._client.post(
            _TTS_URL,
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": text, "voice": voice},
        )
        response.raise_for_status()
        latency_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "tts_synthesis_complete",
            chars=len(text),
            latency_ms=latency_ms,
            voice=voice,
        )
        return response.content, latency_ms

    async def close(self) -> None:
        """Close underlying httpx client. Call in lifespan shutdown."""
        await self._client.aclose()
    