"""DEPRECATED — do NOT run this. Kept only for reference.

The docker bridge port 10.200.0.1:7897 is now supplied directly by the home host's
SSH reverse tunnel (`-R 10.200.0.1:7897:127.0.0.1:7897`, with the server's sshd set
to `GatewayPorts clientspecified`). Running this relay would bind that same port, and
on the tunnel's next reconnect SSH (ExitOnForwardFailure) could not rebind and would
exit — taking geo down. The home reconnect loop also `fuser -k 7897/tcp`s on each
cycle, which kept killing this relay anyway. See CLAUDE.md / memory network-proxy-setup.

--- original description (historical) ---

Host-side relay that exposes the home US-VPN proxy on the docker bridge.

Part of the gated geo fix (HOLO_VM_PROXY). The OSWorld VM's default route is the
campus network (China geo); to make geo-sensitive web tasks see the intended US
locale we route the VM's web traffic through the user's home VPN proxy
(127.0.0.1:7897, egress US-LA). The VM can reach the docker bridge gateway
(10.200.0.1) directly, but the proxy is bound to host loopback — so this relay
bridges them, without touching the proxy config:

    10.200.0.1:7897  ->  127.0.0.1:7897   (home VPN proxy, US)

Hardened: per-socket timeouts reap hung connections (so threads/fds don't pile up
under the eval's many concurrent connections), and the accept loop catches EVERY
exception so the relay never crashes. run_multi.ensure_relay() also (re)starts it
before each pass as a backstop.

Run:
    setsid python3 holo_repro/proxy_relay.py >/tmp/proxy_relay.log 2>&1 &
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

LISTEN = (os.environ.get("HOLO_RELAY_BIND", "10.200.0.1"), 7897)
UPSTREAM = ("127.0.0.1", 7897)
IDLE_TIMEOUT = 300  # seconds; close a connection idle this long so threads get reaped


def _close(*socks) -> None:
    for s in socks:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        _close(src, dst)


def _handle(client: socket.socket) -> None:
    try:
        client.settimeout(IDLE_TIMEOUT)
        up = socket.create_connection(UPSTREAM, timeout=10)
        up.settimeout(IDLE_TIMEOUT)
    except Exception:
        _close(client)
        return
    threading.Thread(target=_pipe, args=(client, up), daemon=True).start()
    threading.Thread(target=_pipe, args=(up, client), daemon=True).start()


def main() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(512)
    print(f"proxy relay listening {LISTEN} -> {UPSTREAM}", flush=True)
    while True:
        try:
            client, _ = srv.accept()
            threading.Thread(target=_handle, args=(client,), daemon=True).start()
        except Exception as e:  # never let the relay die on a transient error
            print(f"relay loop error (continuing): {e}", file=sys.stderr, flush=True)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
