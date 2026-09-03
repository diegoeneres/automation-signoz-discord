from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider

    def shutdown(self) -> None:
        """Flush pending telemetry before the process exits."""
        self.logger_provider.shutdown()
        self.meter_provider.shutdown()
        self.tracer_provider.shutdown()


def configure_telemetry(app: FastAPI) -> Telemetry | None:
    """Configure OTLP/HTTP exporters using standard OTEL_* environment variables."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true"
    if not endpoint or disabled:
        return None

    resource = Resource.create(
        {"service.name": os.getenv("OTEL_SERVICE_NAME", "signoz-discord-jira")}
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))
    log_level_name = os.getenv("OTEL_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.getLogger("app").setLevel(log_level)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    SQLite3Instrumentor().instrument()
    SystemMetricsInstrumentor().instrument(meter_provider=meter_provider)
    logging.getLogger(__name__).info(
        "OpenTelemetry habilitado para traces, metricas e logs; service.name=%s",
        os.getenv("OTEL_SERVICE_NAME", "signoz-discord-jira"),
    )
    return Telemetry(tracer_provider, meter_provider, logger_provider)


meter = metrics.get_meter("signoz-discord-jira")
alerts_received = meter.create_counter("app.alerts.received", unit="{alert}")
notifications_sent = meter.create_counter("app.notifications.sent", unit="{notification}")
notification_failures = meter.create_counter("app.notifications.failures", unit="{failure}")
tickets_created = meter.create_counter("app.jira.tickets.created", unit="{ticket}")
