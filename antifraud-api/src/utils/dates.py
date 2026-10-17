from datetime import datetime


def parse_moment(value: str) -> datetime:
    """ISO 8601 com fuso. O "Z" vira +00:00 para o fromisoformat."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
