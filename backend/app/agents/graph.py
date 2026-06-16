import asyncio

from langgraph.graph import END, StateGraph
from app.agents.nodes.coach import CoachNode
from app.agents.nodes.evaluator import EvaluatorNode
from app.agents.nodes.interviewer import InterviewerNode
from app.agents.state import InterviewState, QAPair

MAX_QUESTIONS = 5

_evaluator = EvaluatorNode()
_interviewer = InterviewerNode()
_coach = CoachNode()

# Set at app startup via init_interview_graph().
# Module-level ref so session_service.py import stays unchanged.
# None until lifespan completes — any call before startup will raise immediately.
interview_graph = None


async def generate_question_node(state: InterviewState) -> dict:
    """
    Calls InterviewerNode to generate the next question.
    Appends a new QAPair (no transcript yet) to qa_history.
    Does NOT increment current_sequence — that happens in process_answer_node.
    """
    result = await _interviewer.generate_question(
        role=state["role"],
        difficulty=state["difficulty"],
        sequence=state["current_sequence"],
        qa_history=state["qa_history"],
        last_scores=state.get("last_scores"),
    )

    new_qa: QAPair = {
        "question_id": "",
        "question_text": result["question"],
        "sequence": state["current_sequence"],
        "answer_id": None,
        "transcript": None,
        "scores": None,
    }

    return {
        "next_question": result["question"],
        "qa_history": state["qa_history"] + [new_qa],
    }


async def process_answer_node(state: InterviewState) -> dict:
    """
    Evaluate and coach the latest answer IN PARALLEL via asyncio.gather.

    WHY asyncio.gather here (not two sequential awaits):
      Two separate awaits: total_latency = eval_time + coach_time
      asyncio.gather:      total_latency = max(eval_time, coach_time)
      Both call Groq LLM — each takes ~500-1500ms. Gather saves ~50% wall time.

    Updates qa_history with eval scores.
    Increments current_sequence.
    Sets is_complete if MAX_QUESTIONS reached.
    """
    last_qa = state["qa_history"][-1]
    transcript = last_qa.get("transcript") or ""
    question_text = last_qa["question_text"]

    eval_result, coach_result = await asyncio.gather(
        _evaluator.evaluate(
            question=question_text,
            transcript=transcript,
            role=state["role"],
            difficulty=state["difficulty"],
        ),
        _coach.analyze(transcript=transcript),
    )

    updated_history = list(state["qa_history"])
    updated_history[-1] = {**last_qa, "scores": eval_result}

    next_sequence = state["current_sequence"] + 1
    is_complete = next_sequence > MAX_QUESTIONS

    return {
        "qa_history": updated_history,
        "last_scores": eval_result,
        "last_coach_result": coach_result,
        "current_sequence": next_sequence,
        "is_complete": is_complete,
    }


def route_after_answer(state: InterviewState) -> str:
    """
    Conditional edge function — decides graph routing after processing an answer.
    Returns key that maps to a node name in add_conditional_edges.
    """
    if state.get("is_complete"):
        return "end"
    return "generate_question"


def build_interview_graph(checkpointer):
    """
    Construct and compile the LangGraph interview graph.

    checkpointer is injected — NOT created here. This keeps graph construction
    pure and testable (pass MemorySaver in tests, AsyncPostgresSaver in prod).

    Called once from init_interview_graph() at app startup — NOT at module load.
    Module-level singleton (interview_graph) is set after this returns.
    """
    builder = StateGraph(InterviewState)

    builder.add_node("generate_question", generate_question_node)
    builder.add_node("process_answer", process_answer_node)

    builder.set_entry_point("generate_question")
    builder.add_edge("generate_question", "process_answer")

    builder.add_conditional_edges(
        "process_answer",
        route_after_answer,
        {
            "generate_question": "generate_question",
            "end": END,
        },
    )

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["process_answer"],
    )


async def init_interview_graph(database_url: str) -> None:
    """
    Initialize AsyncPostgresSaver and compile the interview graph.

    Called ONCE from FastAPI lifespan at startup — before any request is served.
    Sets the module-level `interview_graph` ref used by session_service.py.

    WHY AsyncPostgresSaver.setup() instead of Alembic migration:
      - setup() is idempotent — safe to call every startup
      - checkpoint schema is owned by langgraph, not your app
      - langgraph may change schema between versions
      - manual Alembic migration would drift and break on upgrades
      - do NOT duplicate langgraph's internal schema in your migrations

    WHY psycopg (v3) not psycopg2:
      - AsyncPostgresSaver requires psycopg v3 async interface
      - psycopg2 has no native async support
      - install: pip install "psycopg[async]" langgraph-checkpoint-postgres
    """
    global interview_graph

    # Import here — psycopg[async] + langgraph-checkpoint-postgres must be installed
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    # Connection pool for checkpointer — separate from SQLAlchemy pool.
    # AsyncPostgresSaver uses psycopg3 directly, not SQLAlchemy.
    # min_size=1 at startup, max_size scales under load.
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=10,
        open=False,  # open manually so we control timing
        kwargs={"autocommit": True},
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)

    # Creates checkpoints, checkpoint_blobs, checkpoint_writes,
    # checkpoint_migrations tables if they don't exist.
    # Idempotent — safe on every startup.
    await checkpointer.setup()

    interview_graph = build_interview_graph(checkpointer)
    