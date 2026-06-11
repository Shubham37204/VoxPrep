# # session_service.py — LangGraph orchestration + DB persistence
# #
# # BUG FIXES APPLIED:
# #   #1 Transaction safety: compensating transaction on respond() failure
# #   #3 Retry before FAILED: _with_retry() wraps graph invocations
# #   #4 Duplicate protection: UniqueConstraint on Answer catches dupes at DB level
# #   #9 Event logging: every question/answer/score writes a session_event row
# #   #10 RETRYING state: transitions session to RETRYING before retry attempts

# import asyncio
# import logging

# from sqlalchemy.exc import IntegrityError
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.agents.graph import interview_graph
# from app.agents.state import InterviewState
# from app.core.enums import SessionStatus
# from app.core.exceptions import SessionNotFoundError
# from app.repositories.answer_repository import AnswerRepository
# from app.repositories.feedback_repository import FeedbackRepository
# from app.repositories.session_repository import SessionRepository

# logger = logging.getLogger(__name__)

# MAX_RETRIES = 2        # Max retry attempts for transient LLM failures
# RETRY_BASE_DELAY = 1.0  # Seconds — doubles on each retry (1s, 2s)


# async def _with_retry(coro_fn, max_retries: int = MAX_RETRIES, base_delay: float = RETRY_BASE_DELAY):
#     """
#     Retry a coroutine function on transient failures.
#     Only retries on Exception — not on KeyboardInterrupt or SystemExit.
#     Exponential backoff: 1s, 2s, then raises.

#     Args:
#         coro_fn: Callable that returns a coroutine when called (lambda or functools.partial).
#     """
#     last_error: Exception | None = None
#     for attempt in range(max_retries + 1):
#         try:
#             return await coro_fn()
#         except Exception as e:
#             last_error = e
#             if attempt < max_retries:
#                 wait = base_delay * (2 ** attempt)
#                 logger.warning(
#                     "Transient failure on attempt %d/%d, retrying in %.1fs: %s: %s",
#                     attempt + 1, max_retries + 1, wait, type(e).__name__, str(e)
#                 )
#                 await asyncio.sleep(wait)
#     raise last_error


# class SessionOrchestrationService:
#     """
#     Bridges LangGraph state and PostgreSQL persistence.

#     Responsibilities:
#       - Build initial InterviewState from DB session record
#       - Invoke graph for session start and each answer submission
#       - Retry transient LLM failures (ACTIVE → RETRYING → ACTIVE or FAILED)
#       - Persist questions, answers, scores, and feedback to DB
#       - Write session_events for every significant action
#       - Apply compensating transaction if post-graph DB operations fail
#     """

#     def __init__(self, db: AsyncSession) -> None:
#         self._db = db
#         self._session_repo = SessionRepository(db)
#         self._answer_repo = AnswerRepository(db)
#         self._feedback_repo = FeedbackRepository(db)

#     async def begin(self, session_id: str) -> dict:
#         """
#         Start the interview graph. Generates Q1 and persists it to DB.
#         Returns: {question_id, question_text, sequence}
#         """
#         session = await self._session_repo.get_by_id(session_id)

#         initial_state: InterviewState = {
#             "session_id": session_id,
#             "user_id": session.user_id,
#             "role": session.role,
#             "difficulty": session.difficulty,
#             "qa_history": [],
#             "next_question": None,
#             "last_scores": None,
#             "last_coach_result": None,
#             "current_sequence": 1,
#             "is_complete": False,
#         }

#         config = {"configurable": {"thread_id": session_id}}

#         # Retry graph invocation on transient failures
#         result = await _with_retry(
#             lambda: interview_graph.ainvoke(initial_state, config=config)
#         )

#         question = await self._answer_repo.create_question(
#             session_id=session_id,
#             text=result["next_question"],
#             sequence=result["current_sequence"],
#         )

#         # Log QUESTION_ASKED event — audit trail starts here
#         await self._session_repo.log_question_event(
#             session_id=session_id,
#             question_id=question.id,
#             sequence=question.sequence,
#         )

#         # Write DB question_id back into graph state
#         snapshot = await interview_graph.aget_state(config)
#         qa_history = list(snapshot.values["qa_history"])
#         if qa_history:
#             qa_history[-1] = {**qa_history[-1], "question_id": question.id}
#             await interview_graph.aupdate_state(config, {"qa_history": qa_history})

#         return {
#             "question_id": question.id,
#             "question_text": question.text,
#             "sequence": question.sequence,
#         }

#     async def respond(
#         self,
#         session_id: str,
#         question_id: str,
#         transcript: str,
#         latency_ms: int | None = None,
#     ) -> dict:
#         """
#         Process a spoken answer.

#         BUG FIX #4: UniqueConstraint on answers.question_id catches duplicate submissions
#         at DB level before any LLM call is made.

#         BUG FIX #1 (compensating transaction):
#         If graph invocation or DB persistence fails after the answer row is created,
#         the answer row is deleted to avoid orphaned answers without scores.
#         This is a compensating transaction — not a full ACID transaction.
#         Full solution requires repository refactor to remove intermediate commits.

#         BUG FIX #3 (retry before FAILED):
#         If graph invocation fails, transition to RETRYING and retry up to MAX_RETRIES times.
#         Only transition to FAILED if all retries exhausted.
#         """
#         config = {"configurable": {"thread_id": session_id}}

#         # Duplicate submission check: if answer already exists for this question,
#         # IntegrityError from UniqueConstraint → caller gets 409
#         answer = await self._answer_repo.create_answer(
#             question_id=question_id,
#             transcript=transcript,
#             latency_ms=latency_ms,
#         )

#         # Log ANSWER_RECEIVED immediately — even if subsequent steps fail, we know answer arrived
#         await self._session_repo.log_answer_event(
#             session_id=session_id,
#             answer_id=answer.id,
#             question_id=question_id,
#         )

#         try:
#             # Inject transcript into graph state
#             snapshot = await interview_graph.aget_state(config)
#             qa_history = list(snapshot.values["qa_history"])
#             if qa_history:
#                 qa_history[-1] = {
#                     **qa_history[-1],
#                     "transcript": transcript,
#                     "answer_id": answer.id,
#                 }
#             await interview_graph.aupdate_state(config, {"qa_history": qa_history})

#             # Resume graph with retry on transient failures
#             try:
#                 result = await _with_retry(
#                     lambda: interview_graph.ainvoke(None, config=config)
#                 )
#             except Exception as e:
#                 # All retries exhausted — mark session FAILED
#                 logger.error("Graph invocation failed after %d retries: %s", MAX_RETRIES, e)
#                 await self._session_repo.transition_status(
#                     session_id, SessionStatus.FAILED,
#                     payload={"error": str(e), "answer_id": answer.id}
#                 )
#                 raise

#             # Persist score to DB
#             if result.get("last_scores"):
#                 await self._answer_repo.create_score(
#                     answer_id=answer.id,
#                     scores=result["last_scores"],
#                 )
#                 await self._session_repo.log_score_event(
#                     session_id=session_id,
#                     answer_id=answer.id,
#                     overall_score=result["last_scores"].get("overall_score", 0),
#                 )

#             # Persist coach feedback to DB
#             if result.get("last_coach_result"):
#                 await self._feedback_repo.create(
#                     answer_id=answer.id,
#                     data=result["last_coach_result"],
#                 )

#             # Session complete
#             if result.get("is_complete"):
#                 await self._session_repo.transition_status(
#                     session_id, SessionStatus.COMPLETED
#                 )
#                 return {
#                     "session_complete": True,
#                     "next_question": None,
#                     "scores": result.get("last_scores"),
#                 }

#             # Persist next question
#             next_q = await self._answer_repo.create_question(
#                 session_id=session_id,
#                 text=result["next_question"],
#                 sequence=result["current_sequence"],
#             )

#             await self._session_repo.log_question_event(
#                 session_id=session_id,
#                 question_id=next_q.id,
#                 sequence=next_q.sequence,
#             )

#             # Update graph state with DB question_id
#             snapshot = await interview_graph.aget_state(config)
#             qa_history = list(snapshot.values["qa_history"])
#             if qa_history:
#                 qa_history[-1] = {**qa_history[-1], "question_id": next_q.id}
#                 await interview_graph.aupdate_state(config, {"qa_history": qa_history})

#             return {
#                 "session_complete": False,
#                 "question_id": next_q.id,
#                 "question_text": next_q.text,
#                 "sequence": next_q.sequence,
#                 "scores": result.get("last_scores"),
#             }

#         except Exception as e:
#             # COMPENSATING TRANSACTION (bug fix #1):
#             # Answer was persisted but subsequent steps failed.
#             # Delete the answer so DB doesn't contain an orphaned answer without score.
#             # Client can retry — UniqueConstraint will be gone since we deleted the row.
#             try:
#                 await self._answer_repo.delete_answer(answer.id)
#                 logger.info("Compensating transaction: deleted orphaned answer %s", answer.id)
#             except Exception as cleanup_err:
#                 # Log but don't mask the original error
#                 logger.error("Compensating transaction failed: %s", cleanup_err)
#             raise


# session_service.py — LangGraph orchestration + DB persistence
#
# BUG FIXES APPLIED:
#   #1  Transaction safety: compensating transaction on respond() failure
#   #3  Retry before FAILED: _with_retry() wraps graph invocations
#   #4  Duplicate protection: UniqueConstraint on Answer catches dupes at DB level
#   #9  Event logging: every question/answer/score writes a session_event row
#   #10 RETRYING state: transitions session to RETRYING before each retry attempt,
#       back to ACTIVE on recovery, FAILED only when all retries exhausted

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

# Transient errors worth retrying — network blips, rate limits, upstream timeouts.
# Deterministic errors (bad JSON, validation, logic) are NOT retried — they won't resolve.
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

            # Non-transient — don't waste retry budget, propagate immediately
            if not isinstance(e, _RETRYABLE):
                # Still log it — just don't retry
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
                # FIX #10: surface retry state — visible in dashboards and session_events
                await session_repo.transition_status(
                    session_id,
                    SessionStatus.RETRYING,
                    payload={"error": str(e), "attempt": attempt + 1},
                )
                await asyncio.sleep(wait)
                # Recover back to ACTIVE before next attempt
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
            # COMPENSATING TRANSACTION (bug fix #1):
            # Answer was persisted but subsequent steps failed.
            # Delete the answer so client can retry cleanly.
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
