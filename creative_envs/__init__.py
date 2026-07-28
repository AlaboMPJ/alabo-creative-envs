"""Creative-tool environments, exposed to the verifiers spec.

The graders under `environments/*/tests/grader.py` are the real work and stay
the source of truth: they are the ones tested against the actual libraries, and
they run standalone in a container with no ML dependency at all.

This module is a thin adapter so the same graders can be loaded by the verifiers
runtime and pushed to the Environments Hub. Deliberately thin, because two
implementations of a reward function will drift and the wrong one will be the
one somebody trains against.

    import creative_envs
    env = creative_envs.load_environment("exr_render_repair")
"""
from .loader import load_environment, ENVIRONMENTS  # noqa: F401

__all__ = ["load_environment", "ENVIRONMENTS"]
