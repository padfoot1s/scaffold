"""OpenTelemetry setup. Local console (or OTLP) by default; Application Insights via config."""

from __future__ import annotations

import logging
import sys

from agent_framework.observability import (
    configure_otel_providers,
    create_resource,
    disable_instrumentation,
    enable_instrumentation,
)

from inswa.config import Settings

logger = logging.getLogger(__name__)
_configured = False


def setup_telemetry(settings: Settings) -> None:
    """Configure exporters once per process according to TELEMETRY__EXPORTER."""
    global _configured
    if _configured:
        return
    cfg = settings.telemetry
    match cfg.exporter:
        case "none":
            disable_instrumentation()
        case "console":
            from opentelemetry.sdk._logs.export import ConsoleLogExporter
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            # stderr keeps telemetry out of the CLI's answer output on stdout.
            configure_otel_providers(
                service_name=cfg.service_name,
                exporters=[ConsoleSpanExporter(out=sys.stderr), ConsoleLogExporter(out=sys.stderr)],
                enable_sensitive_data=cfg.sensitive_data,
            )
        case "otlp":
            configure_otel_providers(
                service_name=cfg.service_name,
                otlp_endpoint=cfg.otlp_endpoint,
                otlp_protocol="grpc",
                enable_sensitive_data=cfg.sensitive_data,
            )
        case "appinsights":
            if not cfg.appinsights_connection_string:
                raise ValueError(
                    "TELEMETRY__APPINSIGHTS_CONNECTION_STRING (or APPLICATIONINSIGHTS_CONNECTION_STRING) "
                    "must be set when TELEMETRY__EXPORTER=appinsights."
                )
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=cfg.appinsights_connection_string,
                resource=create_resource(service_name=cfg.service_name),
                sampling_ratio=cfg.sampling_ratio,
            )
            enable_instrumentation(enable_sensitive_data=cfg.sensitive_data)
    _configured = True
    logger.info("Telemetry configured with exporter=%s", cfg.exporter)
