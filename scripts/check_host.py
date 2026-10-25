"""Validate the strategy runtime's module and dependency boundaries."""

import ast

from build_strategy import client_side_module, collect_sources

FORBIDDEN_CALLS = {"open", "io.open", "os.open", "os.makedirs", "socket.socket"}


def check():
    sources = collect_sources()
    violations = []
    for name, source in sources.items():
        if client_side_module(name):
            violations.append("client-side module in host graph: " + name)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in FORBIDDEN_CALLS:
                violations.append("%s:%d: %s" % (name, node.lineno, ast.unparse(node.func)))
    if violations:
        raise SystemExit("\n".join(violations))
    return len(sources)


if __name__ == "__main__":
    print("Host graph: %d modules; runtime boundary checks passed" % check())
