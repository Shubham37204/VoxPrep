# from opentelemetry import trace
# from opentelemetry.sdk.resources import Resource
# from opentelemetry.sdk.trace import TracerProvider
# from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# _provider: TracerProvider | None = None


# def configure_tracing(
#     service_name: str = "voxprep",
#     endpoint: str | None = None,
#     export_to_console: bool = False,
# ) -> None:
#     """
#     Initialize the global OTel TracerProvider. Call once at startup.
#     Idempotent — subsequent calls are no-ops (safe for test harnesses and
#     lifespan restarts). Shutdown clears the guard, allowing re-init.

#     Args:
#         service_name:      Appears in every span — identifies this service in dashboards.
#         endpoint:          OTel collector gRPC URL (e.g. 'http://localhost:4317').
#                            Required for production. If None, spans are not exported.
#         export_to_console: Print completed spans to stdout — development only.
#     """
#     global _provider
#     if _provider is not None:
#         return

#     resource = Resource.create({"service.name": service_name})
#     provider = TracerProvider(resource=resource)

#     if export_to_console:
#         provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
#     elif endpoint:
#         from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
#         provider.add_span_processor(
#             BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
#         )
#     trace.set_tracer_provider(provider)
#     _provider = provider


# def get_tracer(name: str) -> trace.Tracer:
#     """
#     Get a tracer bound to a module name.
#     The name appears as the instrumentation scope in trace UIs.
#     """
#     return trace.get_tracer(name)


# def shutdown_tracing() -> None:
#     """Flush buffered spans and shut down. Call in application lifespan shutdown."""
#     global _provider
#     if _provider:
#         _provider.shutdown()
#         _provider = None


from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_provider: TracerProvider | None = None


def configure_tracing(
    service_name: str = "voxprep",
    endpoint: str | None = None,
    export_to_console: bool = False,
) -> None:
    """
    Initialize the global OTel TracerProvider. Idempotent — safe to call
    multiple times in the same process (test harnesses, lifespan restarts).

    Double-init guard checks BOTH our module variable AND OTel's global state.
    shutdown_tracing() resets both, allowing re-init after intentional shutdown.
    """
    global _provider

    # Guard 1: our module variable
    if _provider is not None:
        return

    # Guard 2: OTel global state — catches the case where shutdown_tracing()
    # reset our variable but OTel's internal global still has a real provider.
    # This is what causes "Overriding of current TracerProvider is not allowed".
    existing = trace.get_tracer_provider()
    if isinstance(existing, SDKTracerProvider):
        _provider = existing   # re-adopt the existing provider, no re-init
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if export_to_console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )

    trace.set_tracer_provider(provider)
    _provider = provider


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """Flush buffered spans and shut down. Call in application lifespan shutdown."""
    global _provider
    if _provider:
        _provider.shutdown()
        _provider = None
        