import pytest
from pydantic import ValidationError

from inswa.infra import telemetry
from tests.conftest import make_settings


def test_sampling_ratio_defaults_to_keeping_every_trace(tmp_path):
    assert make_settings(tmp_path).telemetry.sampling_ratio == 1.0


@pytest.mark.parametrize("ratio", [-0.1, 1.5])
def test_sampling_ratio_must_be_a_fraction(tmp_path, ratio):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, telemetry={"sampling_ratio": ratio})


def test_appinsights_exporter_keeps_whole_traces(tmp_path, monkeypatch):
    """Azure Monitor's own default is a 5 spans/s rate limiter that drops spans inside one request."""
    import azure.monitor.opentelemetry as azure_monitor

    captured = {}
    monkeypatch.setattr(azure_monitor, "configure_azure_monitor", lambda **kw: captured.update(kw))
    monkeypatch.setattr(telemetry, "enable_instrumentation", lambda **kw: None)
    monkeypatch.setattr(telemetry, "_configured", False)

    settings = make_settings(
        tmp_path,
        telemetry={
            "exporter": "appinsights",
            "appinsights_connection_string": "InstrumentationKey=abc",
            "sampling_ratio": 0.25,
        },
    )
    telemetry.setup_telemetry(settings)

    assert captured["sampling_ratio"] == 0.25
    assert captured["connection_string"] == "InstrumentationKey=abc"
