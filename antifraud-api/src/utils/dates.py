from datetime import datetime

from errors import InvalidSchema


def parse_moment(value: str) -> datetime:
    """ISO 8601 com fuso. O "Z" vira +00:00 para o fromisoformat.

    O schema confere o FORMATO (o pattern exige o fuso); quem confere se a
    data EXISTE e esta funcao. "2025-13-04", "2025-02-30" e o fuso "+25:00"
    passam no pattern e nao existem: sem o try, o ValueError virava 500.
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidSchema(f"'{value}' is not a valid date-time")
