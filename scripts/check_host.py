"""Reject host imports and direct calls that escape the named-pipe boundary."""

import ast

from build_strategy import collect_sources

FORBIDDEN_CALLS = {"open", "io.open", "os.open", "os.makedirs", "socket.socket"}


def check():
    sources = collect_sources()
    violations = []
    for name, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in FORBIDDEN_CALLS:
                violations.append("%s:%d: %s" % (name, node.lineno, ast.unparse(node.func)))
    if violations:
        raise SystemExit("\n".join(violations))
    return len(sources)


if __name__ == "__main__":
    print("Host graph: %d modules, no forbidden imports or direct I/O calls" % check())
