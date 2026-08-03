"""Deterministic relationship-extraction rules: given two co-occurring,
already-trusted entities and the chunk text connecting them, decide
whether the evidence supports a specific, named relationship. No rule
ever runs an LLM or infers a relationship without a concrete textual (or
structural) connector - see types.py for the evaluate() contract every
rule implements."""
