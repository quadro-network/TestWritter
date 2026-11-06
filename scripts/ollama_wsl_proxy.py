#!/usr/bin/env python3
"""Forward Docker-bridge:11434 -> 127.0.0.1:11434 (Windows Ollama via WSL mirrored localhost)."""
import socket
import threading
import sys

LISTEN_HOST = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
LISTEN_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 11434
TARGET = ("127.0.0.1", 11434)

def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except Exception:
        pass
    finally:
        try: a.shutdown(socket.SHUT_RD)
        except Exception: pass
        try: b.shutdown(socket.SHUT_WR)
        except Exception: pass

def handle(client):
    remote = socket.create_connection(TARGET, timeout=30)
    threading.Thread(target=pipe, args=(client, remote), daemon=True).start()
    pipe(remote, client)
    client.close()
    remote.close()

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(128)
    print(f"ollama proxy {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET[0]}:{TARGET[1]}", flush=True)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

if __name__ == "__main__":
    main()
