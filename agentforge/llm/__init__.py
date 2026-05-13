"""LLM client wrappers used by the multi-agent platform.

Concrete implementations of the four Anthropic-backed Protocols that the
judges, documentation agent, and orchestrator planner expect. Each wrapper
is a thin layer over ``anthropic.Anthropic`` with the Protocol's required
method and structured-output parsing.

Lives at the package root (not under any agent subpackage) so any agent can
import these clients without violating the judge-independence lint. The
Red Team's own client wrappers stay under ``agentforge.redteam.*`` for the
same reason.
"""
