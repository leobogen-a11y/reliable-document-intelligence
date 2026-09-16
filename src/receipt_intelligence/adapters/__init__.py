"""Adapters from external dataset and model formats to domain models."""

from receipt_intelligence.adapters.cord import CordAdapterError, adapt_cord_ground_truth

__all__ = ["CordAdapterError", "adapt_cord_ground_truth"]

