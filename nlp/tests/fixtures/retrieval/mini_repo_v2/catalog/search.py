"""Catalog search and recommendation helpers."""

def normalize_sku(sku: str) -> str:
    """Normalize product identifiers for matching."""
    return sku.strip().upper()

def search_catalog(catalog, sku: str) -> bool:
    """Search for a normalized SKU in the catalog."""
    normalized = normalize_sku(sku)
    return catalog.find_available(normalized)

def recommend_alternatives(catalog, sku: str) -> list[str]:
    """Recommend other available products."""
    normalized = normalize_sku(sku)
    return catalog.find_alternatives(normalized)
