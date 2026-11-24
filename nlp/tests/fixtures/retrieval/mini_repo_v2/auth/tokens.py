"""Access token lifecycle helpers."""

def issue_access_token(subject: str) -> str:
    """Create an access token for a subject."""
    return f"access:{subject}"

def validate_access_token(token: str) -> bool:
    """Check the access token prefix."""
    return token.startswith("access:")

def revoke_access_token(token: str, revoked: set[str]) -> None:
    """Add a token to the revocation set."""
    revoked.add(token)
