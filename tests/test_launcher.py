"""Invalid restart requests must leave the running terminal untouched."""

from unittest.mock import Mock

import pytest

from qmtairlock import qmt_launcher


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "exe"},
        {"mode": "unknown", "wait_ready": False},
        {"mode": "login", "wait_ready": False},
        {"mode": "exe", "wait_ready": False, "ready_timeout_seconds": -1},
        {"mode": "exe", "wait_ready": False, "unexpected": True},
    ],
)
def test_invalid_restart_never_closes_qmt(monkeypatch, tmp_path, options):
    (tmp_path / "XtItClient.exe").touch()
    close = Mock()
    monkeypatch.setattr(qmt_launcher, "close_qmt", close)
    with pytest.raises((qmt_launcher.QmtLauncherError, TypeError)):
        qmt_launcher.restart_qmt(str(tmp_path), **options)
    close.assert_not_called()


def test_auto_selects_full_terminal_when_both_executables_exist(monkeypatch, tmp_path):
    (tmp_path / "XtItClient.exe").touch()
    (tmp_path / "XtMiniQmt.exe").touch()
    spawn = Mock()
    monkeypatch.setattr(qmt_launcher, "_spawn", spawn)
    qmt_launcher.open_qmt(str(tmp_path), wait_ready=False)
    assert spawn.call_args.args[0] == [str(tmp_path / "XtItClient.exe")]


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "auto", "settle_seconds": 0},
        {"mode": "exe", "settle_seconds": -1},
        {"mode": "exe", "settle_seconds": float("nan")},
        {"mode": "exe", "settle_seconds": float("inf")},
    ],
)
def test_locked_auto_or_invalid_settle_never_closes_qmt(monkeypatch, tmp_path, options):
    (tmp_path / "XtItClient.exe").touch()
    close = Mock()
    monkeypatch.setattr(qmt_launcher, "close_qmt", close)
    monkeypatch.setattr(qmt_launcher, "session_is_locked", lambda: True)
    with pytest.raises(qmt_launcher.QmtLauncherError):
        qmt_launcher.restart_qmt(str(tmp_path), wait_ready=False, **options)
    close.assert_not_called()
