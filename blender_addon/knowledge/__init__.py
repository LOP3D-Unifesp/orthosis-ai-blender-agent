"""blender_addon.knowledge — Phase 6 knowledge retrieval subpackage.

Public API:
    KnowledgeItem      — typed knowledge item loaded from a .md file
    KnowledgeRetriever — scored, budget-aware retriever
"""

from .corpus import KnowledgeItem
from .retriever import KnowledgeRetriever

__all__ = ["KnowledgeItem", "KnowledgeRetriever"]
