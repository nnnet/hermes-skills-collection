"""desire-to-goal workflow — exports WORKFLOW for the workflow-engine.

This dir is consumed by workflow-engine via:
    python3 /opt/workflow-engine/cli.py --workflow <this-dir> ...
"""
from .config import WORKFLOW

__all__ = ["WORKFLOW"]
