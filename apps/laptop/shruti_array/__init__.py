"""SHRUTI laptop array processor.

A phased-mic-array built from N phones, processed in real time on the laptop.
Modules are designed so each is independently testable: the protocol framing
has no DSP dependency, the sync engine depends only on numpy, and so on.
"""
from __future__ import annotations

__version__ = "0.1.0"
