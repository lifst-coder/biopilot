"""Shared kernel: configuration, database, audit log, immutability guard, LLM gateway.

Every module may import from ``app.core``. ``app.core`` must never import from a
feature module (eln / memory / analysis / partner).
"""
