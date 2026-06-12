from app.services.stt_service import STTService

_stt = STTService()


async def entrypoint(ctx) -> None:
    """
    Called by LiveKit worker runtime when a new room job is dispatched.
    ctx: JobContext — gives access to room, participants, and tracks.
    """
    pass


