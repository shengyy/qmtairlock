"""Explicit client configuration; no implicit private-file imports."""

import math


def positive_seconds(value, name="timeout_seconds"):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("%s must be finite and positive" % name)
    return value


def client_config(config=None):
    values = dict(config or {})
    unknown = set(values) - {"pipe", "local_cache"}
    if unknown:
        raise ValueError("unknown client config keys: %s" % ", ".join(sorted(unknown)))
    pipe = dict(values.get("pipe") or {})
    if set(pipe) - {"pipe_name", "relay_command", "connect_timeout_seconds"}:
        raise ValueError("unknown pipe config key")
    pipe.setdefault("pipe_name", "qmtairlock")
    pipe["connect_timeout_seconds"] = positive_seconds(pipe.get("connect_timeout_seconds", 5))
    cache = {"enabled": False, "dir": None, "format": "parquet", "fallback_rpc": False}
    cache.update(values.get("local_cache") or {})
    if set(cache) - {"enabled", "dir", "format", "fallback_rpc"}:
        raise ValueError("unknown local_cache config key")
    if cache["format"] != "parquet" or cache["fallback_rpc"] is not False:
        raise ValueError("local cache is Parquet only and reads never call RPC")
    if type(cache["enabled"]) is not bool:
        raise ValueError("local_cache.enabled must be a boolean")
    if cache["enabled"] and not cache["dir"]:
        raise ValueError("local_cache.dir is required when enabled")
    return pipe, cache
