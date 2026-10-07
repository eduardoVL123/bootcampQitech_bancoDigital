from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from constants import BANK_TIMEZONE


def now_utc() -> datetime:
    """O instante de agora, com fuso. Todo horário gravado no banco sai daqui."""
    return datetime.now(timezone.utc)


def bank_today() -> date:
    """O dia de hoje em São Paulo: é nele que se conta a idade e se decide o que é futuro."""
    return now_utc().astimezone(ZoneInfo(BANK_TIMEZONE)).date()
