"""Shared core for turnkey GTM agents.

Everything that must be correct every time (scoring, decay, stacking, dedup,
copy checks, approvals, budgets, audit) lives here as deterministic code.
Agents add a skill, a set of tools and an eval suite on top.
"""

__version__ = "0.1.0"
