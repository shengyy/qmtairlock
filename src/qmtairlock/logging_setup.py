"""Console-only diagnostics, safe in the embedded QMT host."""


class ConsoleLogger:
    def __init__(self, name):
        self.name = name

    def _write(self, level, message, args):
        print("[qmtairlock:%s:%s] %s" % (self.name, level, message % args if args else message))

    def debug(self, message, *args):
        pass

    def info(self, message, *args):
        self._write("info", message, args)

    def warning(self, message, *args):
        self._write("warning", message, args)

    def error(self, message, *args):
        self._write("error", message, args)

    def exception(self, message, *args):
        self._write("error", message, args)


def get_logger(name=""):
    return ConsoleLogger(name)
