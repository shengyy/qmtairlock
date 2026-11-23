"""Build the ASCII, Python 3.12 host strategy from a closed, auditable module graph."""

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_PYTHON = (3, 12)
FORBIDDEN_IMPORTS = {"socket", "redis", "zmq", "pandas", "pyarrow", "subprocess", "xtquant", "pathlib"}


def client_side_module(name):
    return any(
        part.startswith("client") or "_client" in part or "relay" in part or "launcher" in part
        for part in name.split(".")
    )


def module_path(name):
    path = ROOT / "src" / Path(*name.split("."))
    return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")


def collect_sources():
    pending = ["qmtairlock.strategy_runtime", "qmtairlock.qmt_injected"]
    sources = {}
    while pending:
        name = pending.pop()
        if name in sources:
            continue
        if client_side_module(name):
            raise ValueError("client-side module in host graph: " + name)
        path = module_path(name)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, feature_version=HOST_PYTHON)
        sources[name] = source
        parent = name.rpartition(".")[0]
        if parent:
            pending.append(parent)
        package = name if path.name == "__init__.py" else parent
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level:
                    mod = importlib.util.resolve_name("." * node.level + mod, package)
                imported = [mod]
                if mod.startswith("qmtairlock") and module_path(mod).name == "__init__.py":
                    imported += [
                        mod + "." + alias.name for alias in node.names if module_path(mod + "." + alias.name).exists()
                    ]
            for mod in imported:
                if mod.split(".")[0] in FORBIDDEN_IMPORTS or mod == "logging.handlers":
                    raise ValueError("forbidden host import in %s: %s" % (name, mod))
                if mod == "qmtairlock" or mod.startswith("qmtairlock."):
                    pending.append(mod)
    return dict(sorted(sources.items()))


class Bindings(ast.NodeVisitor):
    def __init__(self):
        self.names = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Import(self, node):
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node):
        if any(alias.name == "*" for alias in node.names):
            raise ValueError("star imports are not supported")
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.names.update(node.names)

    def visit_comprehension(self, node):
        # Comprehension targets live in a separate scope.
        self.visit(node.iter)


def indent_source(source):
    protected = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING:
            protected.update(range(token.start[0], token.end[0]))
    return "".join(
        line if index in protected else "    " + line for index, line in enumerate(source.splitlines(keepends=True))
    )


def _escape(char):
    point = ord(char)
    return "\\u%04x" % point if point <= 0xFFFF else "\\U%08x" % point


def code_constants(code):
    """Every literal value of a code object and its nested bodies, in order."""
    values = []
    for constant in code.co_consts:
        if hasattr(constant, "co_consts"):
            values.extend(code_constants(constant))
        else:
            values.append(constant)
    return values


def ascii_source(source):
    """The same program spelled in ASCII, so the host's source decoding cannot change it.

    Non-ASCII text may only sit in comments and ordinary string literals, where
    ``\\uXXXX`` spells the same character. Any other placement (identifiers, raw
    strings, a preceding backslash) changes the compiled constants and fails here.
    """
    escaped = "".join(char if ord(char) < 128 else _escape(char) for char in source)
    if escaped != source and code_constants(compile(escaped, "<ascii>", "exec")) != code_constants(
        compile(source, "<source>", "exec")
    ):
        raise ValueError("non-ASCII text outside comments and ordinary string literals")
    return escaped


def build(output):
    sources = collect_sources()
    blocks, funcs = [], []
    for index, (name, source) in enumerate(sources.items()):
        visitor = Bindings()
        visitor.visit(ast.parse(source))
        names = sorted(visitor.names)
        decl = "".join(
            "    global " + ", ".join(names[offset : offset + 8]) + "\n" for offset in range(0, len(names), 8)
        )
        blocks.append("\ndef _mod_%d():\n%s%s\n" % (index, decl, indent_source(source)))
        funcs.append("    %r: _mod_%d," % (name, index))
    packages = tuple(name for name in sources if module_path(name).name == "__init__.py")
    body = (ROOT / "scripts/strategy_entry.py").read_text(encoding="utf-8")
    body = body.replace(
        "_MODULE_FUNCS = {}  # Replaced with real module function bodies at build time.",
        "".join(blocks) + "\n_MODULE_FUNCS = {\n" + "\n".join(funcs) + "\n}",
    )
    # Pure ASCII reads the same under any host decoding; the cookie only keeps the documented first line.
    body = "# coding: gbk\n" + ascii_source(body.replace("_PACKAGES = ()", "_PACKAGES = %r" % (packages,)))
    data = body.encode("ascii")
    output = Path(output)
    ast.parse(body, feature_version=HOST_PYTHON)
    code = compile(body, output.name, "exec")
    for constant in code.co_consts:
        if hasattr(constant, "co_name") and constant.co_name.startswith("_mod_") and constant.co_cellvars:
            raise ValueError("module bindings became closure cells: " + constant.co_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    manifest = {
        "schema_version": 1,
        "artifact": output.name,
        "encoding": "ascii",
        "host_python": "%d.%d" % HOST_PYTHON,
        "sha256": hashlib.sha256(data).hexdigest(),
        "modules": {name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()},
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/QMTAIRLOCK.py")
    args = parser.parse_args()
    manifest = build(args.output)
    print("%s: %d modules, sha256 %s" % (args.output, len(manifest["modules"]), manifest["sha256"]))


if __name__ == "__main__":
    main()
