"""Compatibility shim: the client lives in ipc.py."""
from .ipc import Client, ServiceError  # noqa: F401
