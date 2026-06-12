from __future__ import annotations

import io
import time

from groq import AsyncGroq

from app.config.settings import get_settings
from app.observability.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

_MAX_AUDIO_BYTES = 25 * 1024 * 1024   
_SUPPORTED_FORMATS = {
    "audio/webm", "audio/mp4", "audio/mpeg",
    "audio/wav", "audio/ogg", "audio/flac",
}


class STTService:
    """
    Thin async wrapper around Groq Whisper transcription API.
    Returns (transcript, latency_ms) tuple — latency tracked for Prometheus.
    """

    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
    ) -> tuple[str, int]:
        """
        Transcribe audio bytes to text.

        Args:
            audio_bytes: Raw audio file content.
            filename:    Used by Groq to infer format. Include extension.

        Returns:
            (transcript, latency_ms)

        Raises:
            ValueError: Empty audio or file too large — caught before API call
                        to avoid wasting quota on invalid input.
        """
        if not audio_bytes:
            raise ValueError("audio_bytes must not be empty")
        if len(audio_bytes) > _MAX_AUDIO_BYTES:
            raise ValueError(
                f"audio too large: {len(audio_bytes)} bytes exceeds 25MB Groq limit"
            )

        t0 = time.monotonic()
        result = await self._client.audio.transcriptions.create(
            file=(filename, io.BytesIO(audio_bytes)),
            model=settings.GROQ_WHISPER_MODEL,
            response_format="text",
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        transcript = result if isinstance(result, str) else result.text
        logger.info(
            "stt_transcription_complete",
            words=len(transcript.split()),
            latency_ms=latency_ms,
            filename=filename,
        )
        return transcript, latency_ms
    