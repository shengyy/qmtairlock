"""Benchmark local codec/framing only; never connects to a terminal."""

import argparse
import io
import json
import statistics
import time

from qmtairlock.rpc_codec import to_jsonable
from qmtairlock.transports.pipe_relay import read_frame, write_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    payload = {"request_id": "benchmark", "ok": True, "data": {"600000.SH": {"lastPrice": 10.0}}}
    timings = []
    for _ in range(args.iterations):
        start = time.perf_counter_ns()
        raw = json.dumps(to_jsonable(payload)).encode()
        output = io.BytesIO()
        write_frame(output, raw)
        output.seek(0)
        assert json.loads(read_frame(output)) == payload
        timings.append((time.perf_counter_ns() - start) / 1000)
    timings.sort()
    print(
        "Local codec + in-memory relay frame: median %.2f us, p95 %.2f us (%d iterations)"
        % (statistics.median(timings), timings[int((len(timings) - 1) * 0.95)], len(timings))
    )


if __name__ == "__main__":
    main()
