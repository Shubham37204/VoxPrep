from prometheus_client import Counter, Gauge, Histogram

# Sessions
sessions_created_total = Counter(
    "voxprep_sessions_created_total",
    "Total interview sessions created",
    ["role", "difficulty"],
)

sessions_completed_total = Counter(
    "voxprep_sessions_completed_total",
    "Total interview sessions completed",
)

sessions_failed_total = Counter(
    "voxprep_sessions_failed_total",
    "Total interview sessions failed",
    ["reason"],
)

active_sessions = Gauge(
    "voxprep_active_sessions",
    "Currently active interview sessions",
)

# LLM
llm_calls_total = Counter(
    "voxprep_llm_calls_total",
    "Total LLM calls",
    ["node", "model"],
)

llm_latency_seconds = Histogram(
    "voxprep_llm_latency_seconds",
    "LLM latency in seconds",
    ["node"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],   # ← actual LLM range
)

llm_retries_total = Counter(
    "voxprep_llm_retries_total",
    "Total LLM retries",
)

# STT
stt_calls_total = Counter(
    "voxprep_stt_calls_total",
    "Total STT requests",
)

stt_latency_ms = Histogram(
    "voxprep_stt_latency_ms",
    "STT latency in milliseconds",
    buckets=[100, 300, 500, 1000, 2000, 5000],   # ← actual STT range
)

# Answer processing
answer_processing_seconds = Histogram(
    "voxprep_answer_processing_seconds",
    "Time to process answer end-to-end",
)

filler_words_detected_total = Counter(
    "voxprep_filler_words_detected_total",
    "Total filler words detected",
)

# DB
db_operation_seconds = Histogram(
    "voxprep_db_operation_seconds",
    "Database operation latency",
    ["operation"],
)
