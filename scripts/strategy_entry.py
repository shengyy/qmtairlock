"""In-memory module loader and QMT entry callbacks, embedded by build_strategy.py."""

import builtins as _builtins
import types as _types

_previous_runtime = globals().get("_runtime")
if _previous_runtime is not None:
    _previous_runtime.stop()

# QMT_CONFIG_BEGIN
QMT_ACCOUNT_ID = ""
QMT_RPC_CONFIG = {
    "account_types": ["STOCK"],
    "allow_order_methods": False,
    "pipe": {"pipe_name": "qmtairlock"},
    "schedule_adjust_interval": "100nMilliSecond",
}
# QMT_CONFIG_END

_MODULE_FUNCS = {}  # Replaced with real module function bodies at build time.
_PACKAGES = ()
_modules = {}
_runtime = None
_original_import = _builtins.__import__


def _load(name):
    if name in _modules:
        return _modules[name]
    if name not in _MODULE_FUNCS:
        raise ImportError("module not in the strategy graph: %s" % name)
    parent_name, _, child = name.rpartition(".")
    parent = _load(parent_name) if parent_name else None
    module = _types.ModuleType(name)
    module.__package__ = name if name in _PACKAGES else parent_name
    if name in _PACKAGES:
        module.__path__ = []
    module.__dict__["__builtins__"] = dict(vars(_builtins), __import__=_local_import)
    _modules[name] = module
    try:
        exec(_MODULE_FUNCS[name].__code__, module.__dict__)
    except Exception:
        _modules.pop(name, None)
        raise
    if parent is not None:
        setattr(parent, child, module)
    return module


def _local_import(name, module_globals=None, module_locals=None, fromlist=(), level=0):
    if level:
        package = (module_globals or {}).get("__package__", "")
        parts = package.split(".")
        if level > len(parts):
            raise ImportError("relative import beyond package")
        name = ".".join(parts[: len(parts) - level + 1]) + ("." + name if name else "")
    if name == "qmtairlock" or name.startswith("qmtairlock."):
        module = _load(name)
        for member in fromlist or ():
            submodule = name + "." + member
            if not hasattr(module, member) and submodule in _MODULE_FUNCS:
                _load(submodule)
        return module if fromlist else _load("qmtairlock")
    return _original_import(name, module_globals, module_locals, fromlist, 0)


def init(ContextInfo):
    global _runtime
    if _runtime is not None:
        _runtime.stop()
    injected = _load("qmtairlock.qmt_injected").capture_qmt_injected_funcs(globals())
    runtime_type = _load("qmtairlock.strategy_runtime").StrategyRuntime
    _runtime = runtime_type(ContextInfo, QMT_ACCOUNT_ID, QMT_RPC_CONFIG, injected)
    _runtime.start()
    return _runtime


def after_init(ContextInfo):
    return adjust(ContextInfo)


def adjust(ContextInfo):
    return _runtime.adjust() if _runtime is not None else None


def handlebar(ContextInfo):
    return adjust(ContextInfo)


def stop(ContextInfo=None):
    global _runtime
    if _runtime is not None:
        _runtime.stop()
        _runtime = None


def order_callback(ContextInfo, orderInfo):
    if _runtime is not None:
        return _runtime.order_callback(orderInfo)


def credit_account_callback(ContextInfo, seq, result):
    if _runtime is not None:
        return _runtime.credit_account_callback(seq, result)
