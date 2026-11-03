"""Partner module — Layer 4: interpretation, critique, hypotheses, proposals, decisions.

Consumes ELN, Memory and Analysis *only* through their service interfaces. Never
computes analytical numbers itself: every number it shows is an :class:`Evidence`
value copied from a stored record.
Public interface: :mod:`app.partner.service`, :mod:`app.partner.schemas`.
"""
