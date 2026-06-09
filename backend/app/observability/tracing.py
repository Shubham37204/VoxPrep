# tracing.py — OpenTelemetry distributed tracing setup
#
# WHY OTel alongside Prometheus:
#   Prometheus answers "what" — avg respond() latency is 800ms.
#   OTel answers "why"  — respond() spent 650ms in evaluator, 50ms in DB.
#   They complement each other: Prometheus for alerting, OTel for debugging.
#
# Phase 9 setup:
#   development → ConsoleSpanExporter (prints spans to stdout)
#   production  → OTLPSpanExporter (ships to Jaeger / Grafana Tempo / Datadog)
#
# Usage in services/nodes:
#   tracer = get_tracer(__name__)
#   with tracer.start_as_current_span("evaluate_answer") as span:
#       span.set_attribute("session_id", session_id)
#       span.set_attribute("role", role)
#       result = await evaluator.evaluate(...)

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_provider: TracerProvider | None = None


def configure_tracing(
    service_name: str = "voxprep",
    endpoint: str | None = None,
    export_to_console: bool = False,
) -> None:
    """
    Initialize the global OTel TracerProvider. Call once at startup.

    Args:
        service_name:      Appears in every span — identifies this service in dashboards.
        endpoint:          OTel collector gRPC URL (e.g. 'http://localhost:4317').
                           Required for production. If None, spans are not exported.
        export_to_console: Print completed spans to stdout — development only.
    """
    global _provider

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if export_to_console:
        # Prints spans as JSON when they complete — useful for seeing what's traced
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif endpoint:
        # Ships spans to a real collector — Jaeger, Grafana Tempo, or Datadog
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
    # If neither: NoOp — spans created but immediately discarded (zero overhead)

    trace.set_tracer_provider(provider)
    _provider = provider


def get_tracer(name: str) -> trace.Tracer:
    """
    Get a tracer bound to a module name.
    The name appears as the instrumentation scope in trace UIs.
    """
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """Flush buffered spans and shut down. Call in application lifespan shutdown."""
    global _provider
    if _provider:
        _provider.shutdown()
        _provider = None