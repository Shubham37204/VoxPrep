# graph.py — LangGraph interview graph definition
#
# WHY LangGraph here (not plain Python functions):
#   - Conditional routing based on score (follow-up vs new topic) is a graph problem
#   - Built-in checkpointer persists full conversation state between HTTP requests
#   - interrupt_before lets the graph pause mid-flow and wait for user input
#   - When auth/multi-agent complexity grows, graph branching scales naturally
#
# GRAPH FLOW:
#   First invocation (begin):
#     START → generate_question → [INTERRUPT] ← client receives Q1
#
#   Subsequent invocations (respond):
#     [RESUME] → process_answer → route_after_answer:
#       ├── "generate_question" → generate_question → [INTERRUPT] ← client receives Q2
#       └── "end" → END ← session complete
#
# STATE PERSISTENCE:
#   MemorySaver stores state in RAM — sufficient for Phase 5.
#   Production upgrade path: replace with langgraph.checkpoint.postgres.AsyncPostgresSaver
#   using the same DATABASE_URL. No graph code changes required.

import asyncio

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.nodes.coach import CoachNode
from app.agents.nodes.evaluator import EvaluatorNode
from app.agents.nodes.interviewer import InterviewerNode
from app.agents.state import InterviewState, QAPair

# Max questions before session auto-completes
MAX_QUESTIONS = 5

# Node singletons — instantiated once, reused across all graph invocations
_evaluator = EvaluatorNode()
_interviewer = InterviewerNode()
_coach = CoachNode()


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
        "question_id": "",              # Filled in by service layer after DB persist
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

    # Parallel LLM calls — core Phase 5 feature
    eval_result, coach_result = await asyncio.gather(
        _evaluator.evaluate(
            question=question_text,
            transcript=transcript,
            role=state["role"],
            difficulty=state["difficulty"],
        ),
        _coach.analyze(transcript=transcript),
    )

    # Merge eval scores into the last QAPair
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


def build_interview_graph():
    """
    Construct and compile the LangGraph interview graph.
    Called once at module load — returns a compiled graph ready for invocation.
    """
    builder = StateGraph(InterviewState)

    builder.add_node("generate_question", generate_question_node)
    builder.add_node("process_answer", process_answer_node)

    builder.set_entry_point("generate_question")

    # generate_question always flows to process_answer
    # But interrupt_before=["process_answer"] means the graph PAUSES here
    # and waits for external state update (user's transcript)
    builder.add_edge("generate_question", "process_answer")

    # After processing: route to next question or end
    builder.add_conditional_edges(
        "process_answer",
        route_after_answer,
        {
            "generate_question": "generate_question",
            "end": END,
        },
    )

    memory = MemorySaver()

    return builder.compile(
        checkpointer=memory,
        # Graph pauses BEFORE process_answer — gives service layer time to inject transcript
        interrupt_before=["process_answer"],
    )


# Module-level singleton — thread_id (session_id) isolates state between sessions
# MemorySaver is RAM-only — replace with AsyncPostgresSaver for production persistence
interview_graph = build_interview_graph()
