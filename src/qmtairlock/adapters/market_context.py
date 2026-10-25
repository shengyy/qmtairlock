"""Bound QMT context and injected globals; never imports the xtdata SDK."""


class MarketContext:
    def __init__(self, context_info, qmt_api=None):
        self.context_info = context_info
        self.qmt_api = dict(qmt_api or {})

    def call(self, name, *args, **kwargs):
        method = getattr(self.context_info, name, None)
        if not callable(method):
            raise NotImplementedError("ContextInfo.%s is unavailable" % name)
        return method(*args, **kwargs)

    def call_global_first(self, name, *args, **kwargs):
        method = self.qmt_api.get(name)
        if callable(method):
            return method(*args, **kwargs)
        return self.call(name, *args, **kwargs)

    def first_supported_named(self, shapes):
        last_error = None
        for name, args, kwargs in shapes:
            method = getattr(self.context_info, name, None)
            if not callable(method):
                continue
            try:
                return name, args, kwargs, method(*args, **kwargs)
            except TypeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise NotImplementedError("no supported ContextInfo call shape")

    def first_supported(self, shapes):
        return self.first_supported_named(shapes)[3]
