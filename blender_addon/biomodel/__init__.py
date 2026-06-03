"""Biomodel source-generation helpers.

This package is the staging area for the canonical-source migration.  The
first phase exposes only a source template; later phases can move repeated
raw bpy operations into a small domain-specific helper layer.
"""

from .source_template import (
    BIOMODEL_SOURCE_BLOCK,
    GENERATED_TREE_NAME,
    SOURCE_TEMPLATE_VERSION,
    build_biomodel_source_template,
)

__all__ = [
    "BIOMODEL_SOURCE_BLOCK",
    "GENERATED_TREE_NAME",
    "SOURCE_TEMPLATE_VERSION",
    "build_biomodel_source_template",
]

