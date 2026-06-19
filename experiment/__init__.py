"""Proof-of-concept research harness: is an LLM fit for Vietnamese legal
relation extraction under a precision-first objective?

This package is intentionally isolated from ``src/`` production code. It
*reuses* the production extractor and the ``evaluation/`` matcher + metrics
so that every architecture is scored on exactly the same contract, but it
never modifies them.
"""
