"""Strict listen/accept guards supplement CPython's pre-syscall audit hooks."""

import sys
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import socket


def install(desk):
    originals = {name: getattr(socket.socket, name) for name in ('listen', 'accept', '_accept')}

    def wrapper(name):
        original = originals[name]

        def guarded(sock, *args, **kwargs):
            address = sock.getsockname()
            allowed = (sock.family == socket.AF_INET and sock.type == socket.SOCK_STREAM
                       and type(address) is tuple and len(address) == 2
                       and address[0] == '127.0.0.1' and address[1] in desk.allowed_ports)
            desk.network.append({'event': 'socket.'+name, 'address': address, 'allowed': allowed})
            if not allowed:
                desk.failures.append(['network', 'socket.'+name, str(address)])
                raise OSError('Unregistered listening or accepting socket refused')
            return original(sock, *args, **kwargs)
        return guarded

    for name in originals:
        setattr(socket.socket, name, wrapper(name))
