"""legaledge-kb — the corpus pipeline command line tool.

The pipeline is a batch job, not a service: there is no queue and no worker in
Phase 1.1 (spec §04). Commands are thin wrappers over ``app.services``.
"""

__all__ = ["main"]

from legaledge_kb.main import main
