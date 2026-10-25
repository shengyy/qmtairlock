"""Select the native Windows pipe or its WSL stdio client."""

import os


def build_transport(config, account_id):
    pipe = dict(config)
    relay = pipe.pop("relay_command", None)
    if relay is not None:
        if os.name == "nt":
            raise ValueError("relay_command is only supported by WSL/POSIX clients")
        from .pipe_relay_transport import PipeRelayTransport

        return PipeRelayTransport(relay_command=relay, account_id=account_id, **pipe)
    from .pipe_transport import NamedPipeTransport

    return NamedPipeTransport(account_id=account_id, **pipe)
