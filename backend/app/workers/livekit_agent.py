# livekit_agent.py — LiveKit Agent Worker scaffold (Phase 2 — wired in Phase 3)
#
# PURPOSE:
#   This worker runs as a separate Python process alongside the FastAPI server.
#   It joins a LiveKit room as a "participant", receives the user's audio track,
#   and feeds audio chunks to STTService.
#
# WHY separate process (not inside FastAPI):
#   Audio streaming is long-lived and CPU-bound for decoding.
#   Mixing it into the FastAPI event loop would block HTTP request handling.
#
# CURRENT STATE (Phase 2):
#   Scaffold only — STTService is wired, LiveKit room connection is stubbed.
#   Full wiring happens in Phase 3 when Evaluator + Interviewer nodes are ready.
#
# RUN (when fully wired):
#   python -m app.workers.livekit_agent dev
#
# HOW IT WILL WORK (Phase 3+):
#   1. FastAPI issues a LiveKit access token when a session starts
#   2. This worker receives a JobContext when a user connects
#   3. Worker subscribes to user's audio track
#   4. Audio chunks → STTService.transcribe() → transcript
#   5. Transcript → LangGraph agent pipeline (Evaluator → Interviewer)
#   6. Interviewer response → TTSService → audio back to user via LiveKit

from app.services.stt_service import STTService

# Placeholder — real implementation uses livekit-agents entrypoint
# from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli

_stt = STTService()


async def entrypoint(ctx) -> None:
    """
    Called by LiveKit worker runtime when a new room job is dispatched.
    ctx: JobContext — gives access to room, participants, and tracks.
    """
    # TODO Phase 3: subscribe to user audio track and pipe to _stt.transcribe()
    pass


# if __name__ == "__main__":
#     cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
