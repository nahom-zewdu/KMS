"""Product catalog operations."""

class ProductCatalog:
    """Provides availability and reservation operations."""

    def find_available(self, sku: str) -> bool:
        """Check whether a product can be purchased."""
        return sku in self.available_skus

    def reserve(self, sku: str) -> bool:
        """Reserve one available product."""
        if not self.find_available(sku):
            return False
        self.reserved_skus.add(sku)
        return True

    def release(self, sku: str) -> None:
        """Release a previous reservation."""
        self.reserved_skus.discard(sku)
