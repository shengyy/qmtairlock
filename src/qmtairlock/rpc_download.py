"""Batch history downloads run one native chunk per callback tick."""

import time


class DownloadIncomplete(RuntimeError):
    """The deadline arrived before every chunk ran; ``progress`` names what did."""

    def __init__(self, message, progress):
        super(DownloadIncomplete, self).__init__(message)
        self.progress = progress


class PendingDownload:
    """A native batch download split into code chunks.

    One chunk runs per tick, after that tick's new requests, so ``ping`` and
    other short work wait at most one chunk. A chunk already inside QMT cannot
    be interrupted; the deadline only stops the next chunk from starting.
    """

    def __init__(self, codes, chunk_codes, run_chunk):
        chunk_codes = int(chunk_codes)
        if chunk_codes < 1:
            raise ValueError("download_chunk_codes must be positive")
        self.total = len(codes)
        self.chunks = [list(codes[offset : offset + chunk_codes]) for offset in range(0, len(codes), chunk_codes)]
        self.run_chunk = run_chunk
        self.downloaded = []
        self.last_chunk_seconds = 0.0
        self.deadline = None
        self.request = None
        self.response = None

    def progress(self):
        pending = [code for chunk in self.chunks for code in chunk]
        return {"downloaded": list(self.downloaded), "pending": pending}

    def step(self):
        """Run the next chunk. True when finished; a native failure propagates unchanged."""
        if not self.chunks:
            return True
        started = time.time()
        if self.deadline is not None and started + self.last_chunk_seconds >= self.deadline:
            raise DownloadIncomplete("DownloadIncomplete: %d/%d" % (len(self.downloaded), self.total), self.progress())
        chunk = self.chunks[0]
        self.run_chunk(chunk)
        self.chunks.pop(0)
        self.downloaded.extend(chunk)
        self.last_chunk_seconds = time.time() - started
        return not self.chunks
