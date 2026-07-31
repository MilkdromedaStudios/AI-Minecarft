import socket
import sys

HOST = "127.0.0.1"
PORT = 5050

if len(sys.argv) < 2:
    raise SystemExit("Usage: python send_control.py forward")

action = sys.argv[1].strip().lower()

with socket.create_connection((HOST, PORT), timeout=5) as sock:
    sock.sendall((action + "\n").encode("utf-8"))

print("Sent:", action)
