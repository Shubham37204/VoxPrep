# stt_service.py — Speech-to-text via Groq Whisper
#
# WHY this is a service class (not a plain function):
#   - The Groq client is initialized once and reused across calls (connection pooling)
#   - Easier to mock in tests: patch STTService, not groq internals
#   - Future: swap to Deepgram/AssemblyAI without touching call sites
#
# USAGE:
#   stt = STTService()
#   transcript, latency_ms = await stt.transcribe(audio_bytes, filename="audio.webm")

import time

from groq import AsyncGroq

from app.config.settings import get_settings

settings = get_settings()


class STTService:
    """Wraps Groq Whisper large-v3-turbo for async speech transcription."""

    def __init__(self) -> None:
        # AsyncGroq client — reuse this instance across requests (do not recreate per call)
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
    ) -> tuple[str, int]:
        """
        Submit audio bytes to Groq Whisper and return the transcript.

        Args:
            audio_bytes: Raw audio file bytes. Accepted formats: WebM, WAV, MP3, M4A.
            filename:    Must carry the correct extension — Groq uses it to detect format.
                         Default is WebM because that's what browser MediaRecorder produces.

        Returns:
            (transcript, latency_ms)
            transcript:  Cleaned string with leading/trailing whitespace removed.
            latency_ms:  Wall-clock time from request start to response — stored in answers table.

        Raises:
            groq.APIError: If Groq returns a non-2xx response (rate limit, bad audio, etc.)
        """
        if not audio_bytes:
            # Fail fast — sending empty bytes to Groq wastes quota and returns garbage
            raise ValueError("audio_bytes must not be empty")

        start = time.monotonic()

        transcription = await self._client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=settings.GROQ_WHISPER_MODEL,
            language="en",             # Force English — avoids Whisper guessing wrong language
            response_format="text",    # Return plain string, not {"text": "..."} JSON object
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        # Cast to str because Groq SDK type is ambiguous on response_format="text"
        return str(transcription).strip(), latency_ms
