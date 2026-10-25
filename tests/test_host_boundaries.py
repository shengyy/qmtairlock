"""The host graph must remain independent of client and external-process owners."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("build_strategy")


def test_actual_host_graph_contains_server_and_shared_io_only(builder):
    graph = builder.collect_sources()
    assert "qmtairlock.transports.pipe_server" in graph
    assert "qmtairlock.transports.pipe_native" in graph
    assert not any(builder.client_side_module(name) for name in graph)


@pytest.mark.parametrize(
    "module",
    [
        "qmtairlock.client",
        "qmtairlock.client_callbacks",
        "qmtairlock.transports.pipe_client",
        "qmtairlock.transports.pipe_relay",
        "qmtairlock.transports.pipe_relay_transport",
        "qmtairlock.qmt_launcher",
        "qmtairlock.desktop_launcher",
        "qmtairlock.option_analytics_client",
    ],
)
def test_gate_rejects_client_relay_and_launcher_modules(builder, monkeypatch, module):
    gate = importlib.import_module("check_host")
    monkeypatch.setattr(gate, "collect_sources", lambda: {module: ""})
    with pytest.raises(SystemExit, match="client-side module"):
        gate.check()


def test_builder_rejects_pathlib_before_embedding_source(builder, monkeypatch, tmp_path):
    source = tmp_path / "host.py"
    source.write_text("from pathlib import Path\n")
    monkeypatch.setattr(builder, "module_path", lambda name: source)
    with pytest.raises(ValueError, match="pathlib"):
        builder.collect_sources()
