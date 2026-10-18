from datetime import datetime, timezone

from errors import InvalidSchema

# O motor soma e subtrai dias das datas (janelas de 90 dias, cautelar de 30).
# Perto do ano 1 ou do 9999 a conta sai do calendario do Python e virava 500.
# Nenhuma data legitima de Pix ou de abertura de conta fica fora desta faixa.
FIRST_YEAR = 1900
YEARS_AHEAD = 1


def parse_moment(value: str) -> datetime:
    """ISO 8601 com fuso. O "Z" vira +00:00 para o fromisoformat.

    O schema confere o FORMATO (o pattern exige o fuso); quem confere se a
    data EXISTE e esta funcao. "2025-13-04", "2025-02-30" e o fuso "+25:00"
    passam no pattern e nao existem: sem o try, o ValueError virava 500.
    """
    try:
        momento = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidSchema(f"'{value}' is not a valid date-time")
    ultimo = datetime.now(timezone.utc).year + YEARS_AHEAD
    if not FIRST_YEAR <= momento.year <= ultimo:
        raise InvalidSchema(f"'{value}' is out of range: the year must be between {FIRST_YEAR} and {ultimo}")
    return momento
