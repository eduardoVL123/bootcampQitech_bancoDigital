# A ordem importa: quem e referenciado entra antes de quem referencia.
from models.base import Base
from models.pix_status import PixStatus
from models.fraud_policy import FraudPolicy
from models.pix_account import PixAccount
from models.pix_analysis import PixAnalysis
from models.pix_rule_result import PixRuleResult
from models.account_limit import AccountLimit
from models.reputation_fixture import ReputationFixture
from models.watchlist import Watchlist
from models.ip_range_location import IpRangeLocation
from models.pix_challenge_result import PixChallengeResult
