"""One-use expected denial of the pinned dependency's actual import probe.

This never grants a bind. Code, module, loader stack and constructor provenance
are checked before raising at CPython's pre-syscall audit event.
"""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import hashlib
import importlib.machinery
import importlib._bootstrap
import socket
import threading
import types

SOURCE_SHA = '2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74'
NAME = 'urllib3.util.connection'


class DenialProbe:
    def __init__(self, failures, rows):
        assert NAME not in sys.modules, 'Observation must precede dependency import'
        self.path = Path(sys.prefix) / 'lib/python3.14/site-packages/urllib3/util/connection.py'
        raw = self.path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA
        self.module_code = compile(raw, str(self.path), 'exec', dont_inherit=True)
        self.function_code = next(c for c in self.module_code.co_consts
                                  if isinstance(c, types.CodeType) and c.co_name == '_has_ipv6')
        self.failures, self.rows = failures, rows
        self.count = 0
        self.sockets = {}
        self.lock = threading.Lock()

    def provenance(self, frame):
        module = sys.modules.get(NAME)
        if module is None or frame is None:
            return False
        glob = module.__dict__
        spec = glob.get('__spec__')
        fn = glob.get('_has_ipv6')
        if (frame.f_globals is not glob or type(fn) is not types.FunctionType
                or frame.f_code is not fn.__code__ or frame.f_code != self.function_code
                or spec is None or spec.name != NAME or spec.origin != str(self.path)
                or type(spec.loader) is not importlib.machinery.SourceFileLoader
                or spec.loader.path != str(self.path)):
            return False
        parent = frame.f_back
        if (parent is None or parent.f_globals is not glob or parent.f_code != self.module_code
                or parent.f_lineno != 137):
            return False
        bridge = parent.f_back
        loader = bridge.f_back if bridge is not None else None
        return bool(bridge is not None
                    and bridge.f_code is importlib._bootstrap._call_with_frames_removed.__code__
                    and loader is not None
                    and loader.f_code is importlib.machinery.SourceFileLoader.exec_module.__code__
                    and loader.f_locals.get('module') is module
                    and loader.f_locals.get('self') is spec.loader)

    def audit(self, event, args):
        # Called from the enclosing strict audit hook. Nothing is pre-imported.
        if event == 'socket.__new__':
            sock, family, kind, protocol = args
            frame = sys._getframe(2)
            # socket.socket.__init__ calls _socket.socket.__init__.
            if frame.f_code is socket.socket.__init__.__code__:
                frame = frame.f_back
            if (family == socket.AF_INET6 and kind == socket.SOCK_STREAM and protocol == 0
                    and self.provenance(frame)):
                self.sockets[id(sock)] = sock
            return
        if event != 'socket.bind':
            return
        sock, addr = args
        frame = sys._getframe(2)
        exact = (type(sock) is socket.socket and sock.family == socket.AF_INET6
                 and sock.type == socket.SOCK_STREAM and sock.proto == 0
                 and type(addr) is tuple and len(addr) == 2
                 and type(addr[0]) is str and addr[0] == '::1'
                 and type(addr[1]) is int and addr[1] == 0
                 and self.sockets.get(id(sock)) is sock and self.provenance(frame))
        if exact:
            with self.lock:
                if self.count != 0:
                    self.failures.append(['ipv6-probe-overuse'])
                    raise OSError('Repeated capability probe refused before native bind')
                self.count += 1
                self.rows.append({'event': event, 'address': addr, 'allowed': False,
                                  'expected_denial': True, 'source_sha256': SOURCE_SHA,
                                  'caller': NAME+'._has_ipv6', 'caller_line': frame.f_lineno,
                                  'family': int(sock.family), 'type': int(sock.type), 'protocol': sock.proto,
                                  'fd': sock.fileno(), 'constructor_and_import_stack_verified': True})
            raise OSError('Expected capability denial before native bind')

    def complete(self):
        module = sys.modules.get(NAME)
        if self.count != 1 or module is None or module.HAS_IPV6 is not False:
            self.failures.append(['required-ipv6-denial-unused-or-invalid', self.count])
        if any(sock.fileno() != -1 for sock in self.sockets.values()):
            self.failures.append(['ipv6-probe-socket-not-closed'])
        return {'expected_denials': self.count, 'source_sha256': SOURCE_SHA,
                'has_ipv6': module.HAS_IPV6 if module is not None else None,
                'sockets_closed': all(sock.fileno() == -1 for sock in self.sockets.values())}
