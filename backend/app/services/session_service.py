import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import interview_graph
from app.agents.state import InterviewState
from app.core.enums import SessionStatus
from app.core.exceptions import SessionNotFoundError
from app.observability.logging import get_logger
from app.repositories.answer_repository import AnswerRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.session_repository import SessionRepository

logger = get_logger(__name__)

_RETRYABLE = (
    ConnectionError,
    TimeoutError,
    OSError,
)

MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0


async def _with_retry(
    coro_fn,
    session_repo: SessionRepository,
    session_id: str,
    max_retries: int = MAX_RETRIES,
    base_delay: float = RETRY_BASE_DELAY,
):
    """
    Retry a coroutine on transient failures only.

    Transitions session ACTIVE → RETRYING before each retry attempt,
    RETRYING → ACTIVE on recovery. Only transitions to FAILED after all
    retries exhausted — caller is responsible for that transition.

    Non-retryable exceptions (JSONDecodeError, ValueError, LLM schema errors)
    propagate immediately without sleeping.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except Exception as e:
            last_error = e

            if not isinstance(e, _RETRYABLE):
                logger.warning(
                    "non_retryable_error",
                    session_id=session_id,
                    attempt=attempt + 1,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                raise

            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                logger.warning(
                    "transient_failure_retrying",
                    session_id=session_id,
                    attempt=attempt + 1,
                    max_retries=max_retries + 1,
                    retry_in_seconds=wait,
                    error=str(e),
                )
                await session_repo.transition_status(
                    session_id,
                    SessionStatus.RETRYING,
                    payload={"error": str(e), "attempt": attempt + 1},
                )
                await asyncio.sleep(wait)
                await session_repo.transition_status(
                    session_id,
                    SessionStatus.ACTIVE,
                    payload={"recovered": True, "attempt": attempt + 1},
                )

    raise last_error


class SessionOrchestrationService:
    """
    Bridges LangGraph state and PostgreSQL persistence.

    Transaction model — respond() uses 3 explicit phases:

      Phase 1 (pre-graph, atomic):
        answer + answer_event committed together via explicit await self._db.commit().
        If this fails, nothing is persisted — no cleanup needed.

      Phase 2 (graph, no DB held):
        graph.ainvoke() runs here. Connection released back to pool.
        3-second LLM call does NOT hold a transaction open.

      Phase 3 (post-graph, atomic):
        Fresh AsyncSession from injected factory.
        async with fresh_db.begin() wraps ALL post-graph writes:
          score + score_event + feedback + next_question + question_event + status_transition.
        Auto-commits on clean exit, auto-rolls back on exception.
        If Phase 3 fails → only Phase 1 answer row is orphaned
          → compensating delete on self._db cleans it up.
        No FK children exist yet → compensating delete always succeeds.

    Constructor:
      db: AsyncSession — used for Phase 1 + compensating delete.
      session_factory: async_sessionmaker — used for Phase 3 fresh session.
    """

    def __init__(
        self,
        db: AsyncSession,
        session_factory: async_sessionmaker,
    ) -> None:
        self._db = db
        self._session_factory = session_factory
        self._session_repo = SessionRepository(db)
        self._answer_repo = AnswerRepository(db)
        self._feedback_repo = FeedbackRepository(db)

    async def begin(self, session_id: str) -> dict:
        """
        Start the interview graph. Generates Q1 and persists it to DB.
        Returns: {question_id, question_text, sequence}
        """
        session = await self._session_repo.get_by_id(session_id)

        initial_state: InterviewState = {
            "session_id": session_id,
            "user_id": session.user_id,
            "role": session.role,
            "difficulty": session.difficulty,
            "qa_history": [],
            "next_question": None,
            "last_scores": None,
            "last_coach_result": None,
            "current_sequence": 1,
            "is_complete": False,
        }

        config = {"configurable": {"thread_id": session_id}}

        result = await _with_retry(
            lambda: interview_graph.ainvoke(initial_state, config=config),
            session_repo=self._session_repo,
            session_id=session_id,
        )

        question = await self._answer_repo.create_question(
            session_id=session_id,
            text=result["next_question"],
            sequence=result["current_sequence"],
        )

        await self._session_repo.log_question_event(
            session_id=session_id,
            question_id=question.id,
            sequence=question.sequence,
        )

        snapshot = await interview_graph.aget_state(config)
        qa_history = list(snapshot.values["qa_history"])
        if qa_history:
            qa_history[-1] = {**qa_history[-1], "question_id": question.id}
            await interview_graph.aupdate_state(config, {"qa_history": qa_history})

        return {
            "question_id": question.id,
            "question_text": question.text,
            "sequence": question.sequence,
        }

    async def respond(
        self,
        session_id: str,
        question_id: str,
        transcript: str,
        latency_ms: int | None = None,
    ) -> dict:
        """
        Process a spoken answer.

        UniqueConstraint on answers.question_id catches duplicate submissions
        at DB level before any LLM call is made.

        Three explicit phases — see class docstring for transaction model.
        """
        config = {"configurable": {"thread_id": session_id}}

        # ── Phase 1: persist answer + event, one commit ──────────────────────
        answer = await self._answer_repo.create_answer(
            question_id=question_id,
            transcript=transcript,
            latency_ms=latency_ms,
            commit=False,
        )

        await self._session_repo.log_answer_event(
            session_id=session_id,
            answer_id=answer.id,
            question_id=question_id,
            commit=False,
        )

        await self._db.commit()  # Phase 1 boundary — answer + event land together

        logger.info(
            "phase1_committed",
            session_id=session_id,
            answer_id=answer.id,
        )

        # ── Phase 2: graph — no DB connection held ───────────────────────────
        try:
            snapshot = await interview_graph.aget_state(config)
            qa_history = list(snapshot.values["qa_history"])
            if qa_history:
                qa_history[-1] = {
                    **qa_history[-1],
                    "transcript": transcript,
                    "answer_id": answer.id,
                }
            await interview_graph.aupdate_state(config, {"qa_history": qa_history})

            result = await _with_retry(
                lambda: interview_graph.ainvoke(None, config=config),
                session_repo=self._session_repo,
                session_id=session_id,
            )

        except Exception as e:
            logger.error(
                "graph_failed_all_retries",
                session_id=session_id,
                answer_id=answer.id,
                error=str(e),
            )
            await self._session_repo.transition_status(
                session_id,
                SessionStatus.FAILED,
                payload={"error": str(e), "answer_id": answer.id},
            )
            # Phase 3 never ran — no FK children — compensating delete is safe
            await self._compensate(session_id=session_id, answer_id=answer.id)
            raise

        # ── Phase 3: all post-graph writes — one atomic fresh session ─────────
        try:
            next_q = await self._persist_post_graph(
                session_id=session_id,
                answer_id=answer.id,
                result=result,
                config=config,
            )
        except Exception as e:
            logger.error(
                "phase3_failed",
                session_id=session_id,
                answer_id=answer.id,
                error=str(e),
            )
            # Phase 3 rolled back atomically — only answer row (Phase 1) is orphaned
            await self._compensate(session_id=session_id, answer_id=answer.id)
            raise

        if result.get("is_complete"):
            return {
                "session_complete": True,
                "scores": result.get("last_scores"),
            }

        return {
            "session_complete": False,
            "question_id": next_q.id,
            "question_text": next_q.text,
            "sequence": next_q.sequence,
            "scores": result.get("last_scores"),
        }

    async def _persist_post_graph(
        self,
        session_id: str,
        answer_id: str,
        result: dict,
        config: dict,
    ):
        """
        Phase 3 — atomic post-graph persistence.

        Uses a FRESH AsyncSession from self._session_factory so this transaction
        is completely independent of the Phase 1 session. async with fresh_db.begin()
        auto-commits on clean exit, auto-rolls back on any exception.

        Returns the next Question object if interview continues, else None.
        Graph state (qa_history) is updated AFTER this method returns to keep
        LangGraph state management outside the DB transaction boundary.
        """
        async with self._session_factory() as fresh_db:
            async with fresh_db.begin():
                answer_repo = AnswerRepository(fresh_db)
                session_repo = SessionRepository(fresh_db)
                feedback_repo = FeedbackRepository(fresh_db)

                if result.get("last_scores"):
                    await answer_repo.create_score(
                        answer_id=answer_id,
                        scores=result["last_scores"],
                        commit=False,
                    )
                    await session_repo.log_score_event(
                        session_id=session_id,
                        answer_id=answer_id,
                        overall_score=result["last_scores"].get("overall_score", 0),
                        commit=False,
                    )

                if result.get("last_coach_result"):
                    await feedback_repo.create(
                        answer_id=answer_id,
                        data=result["last_coach_result"],
                        commit=False,
                    )

                if result.get("is_complete"):
                    await session_repo.transition_status(
                        session_id,
                        SessionStatus.COMPLETED,
                        commit=False,
                    )
                    # begin() auto-commits here
                    return None

                next_q = await answer_repo.create_question(
                    session_id=session_id,
                    text=result["next_question"],
                    sequence=result["current_sequence"],
                    commit=False,
                )

                await session_repo.log_question_event(
                    session_id=session_id,
                    question_id=next_q.id,
                    sequence=next_q.sequence,
                    commit=False,
                )
                # begin() auto-commits here

        # Graph state update is OUTSIDE the DB transaction — LangGraph in-memory
        snapshot = await interview_graph.aget_state(config)
        qa_history = list(snapshot.values["qa_history"])
        if qa_history:
            qa_history[-1] = {**qa_history[-1], "question_id": next_q.id}
            await interview_graph.aupdate_state(config, {"qa_history": qa_history})

        logger.info(
            "phase3_committed",
            session_id=session_id,
            answer_id=answer_id,
            next_question_id=next_q.id,
        )

        return next_q

    async def _compensate(self, session_id: str, answer_id: str) -> None:
        """
        Compensating delete for Phase 1 answer row.

        Called when Phase 2 (graph) or Phase 3 (persist) fails.
        Safe to call in both cases because:
          - Phase 2 fail: Phase 3 never ran → no FK children on answer
          - Phase 3 fail: Phase 3 rolled back atomically → no FK children on answer
        FK violation is impossible in either case.
        """
        try:
            await self._answer_repo.delete_answer(answer_id)
            logger.info(
                "compensating_tx_deleted_answer",
                session_id=session_id,
                answer_id=answer_id,
            )
        except Exception as cleanup_err:
            logger.error(
                "compensating_tx_failed",
                session_id=session_id,
                answer_id=answer_id,
                error=str(cleanup_err),
            )
            