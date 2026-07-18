"""LLM agent suite for journal entry testing.

A supervisor agent orchestrates specialist agents (profiling, audit context,
database build, checks, verifier). Every specialist writes its full output as
a structured artifact in the run directory and returns only a compact summary,
so evidence never degrades through supervisor paraphrase.
"""
