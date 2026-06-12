import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import interview_graph
from app.agents.state import InterviewState
from app.core.enums import SessionStatus
from app.core.exceptions import SessionNotFoundError
# FIX #3: structlog, not stdlib
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

    FIX #10: transitions session ACTIVE → RETRYING before each retry attempt,
    RETRYING → ACTIVE on recovery. Only transitions to FAILED after all retries
    exhausted — caller is responsible for that transition.

    FIX (retry discrimination): non-retryable exceptions (JSONDecodeError,
    ValueError, LLM schema errors) propagate immediately without sleeping.
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

    Responsibilities:
      - Build initial InterviewState from DB session record
      - Invoke graph for session start and each answer submission
      - Retry transient LLM failures (ACTIVE → RETRYING → ACTIVE or FAILED)
      - Persist questions, answers, scores, and feedback to DB
      - Write session_events for every significant action
      - Apply compensating transaction if post-graph DB operations fail
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
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

        BUG FIX #4: UniqueConstraint on answers.question_id catches duplicate submissions
        at DB level before any LLM call is made.

        BUG FIX #1 (compensating transaction):
        If graph invocation or DB persistence fails after the answer row is created,
        the answer row is deleted to avoid orphaned answers without scores.
        This is a compensating transaction — not a full ACID transaction.
        Full solution requires repository refactor to remove intermediate commits.

        BUG FIX #3 + #10 (retry + RETRYING state):
        Transient failures trigger ACTIVE → RETRYING → ACTIVE cycle per attempt.
        Only FAILED after all retries exhausted.
        """
        config = {"configurable": {"thread_id": session_id}}

        answer = await self._answer_repo.create_answer(
            question_id=question_id,
            transcript=transcript,
            latency_ms=latency_ms,
        )

        await self._session_repo.log_answer_event(
            session_id=session_id,
            answer_id=answer.id,
            question_id=question_id,
        )

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

            try:
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
                    session_id, SessionStatus.FAILED,
                    payload={"error": str(e), "answer_id": answer.id}
                )
                raise

            if result.get("last_scores"):
                await self._answer_repo.create_score(
                    answer_id=answer.id,
                    scores=result["last_scores"],
                )
                await self._session_repo.log_score_event(
                    session_id=session_id,
                    answer_id=answer.id,
                    overall_score=result["last_scores"].get(
                        "overall_score", 0),
                )

            if result.get("last_coach_result"):
                await self._feedback_repo.create(
                    answer_id=answer.id,
                    data=result["last_coach_result"],
                )

            if result.get("is_complete"):
                await self._session_repo.transition_status(
                    session_id, SessionStatus.COMPLETED
                )
                return {
                    "session_complete": True,
                    "scores": result.get("last_scores"),
                }

            next_q = await self._answer_repo.create_question(
                session_id=session_id,
                text=result["next_question"],
                sequence=result["current_sequence"],
            )

            await self._session_repo.log_question_event(
                session_id=session_id,
                question_id=next_q.id,
                sequence=next_q.sequence,
            )

            snapshot = await interview_graph.aget_state(config)
            qa_history = list(snapshot.values["qa_history"])
            if qa_history:
                qa_history[-1] = {**qa_history[-1], "question_id": next_q.id}
                await interview_graph.aupdate_state(config, {"qa_history": qa_history})

            return {
                "session_complete": False,
                "question_id": next_q.id,
                "question_text": next_q.text,
                "sequence": next_q.sequence,
                "scores": result.get("last_scores"),
            }

        except Exception as e:
            try:
                await self._answer_repo.delete_answer(answer.id)
                logger.info(
                    "compensating_tx_deleted_answer",
                    session_id=session_id,
                    answer_id=answer.id,
                )
            except Exception as cleanup_err:
                logger.error(
                    "compensating_tx_failed",
                    session_id=session_id,
                    answer_id=answer.id,
                    error=str(cleanup_err),
                )
            raise
