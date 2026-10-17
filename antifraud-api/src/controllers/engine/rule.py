from controllers.engine.context import NONE, NOT_EVALUABLE, NOT_TRIGGERED, TRIGGERED, RuleResult


class Rule:
    """Uma regra: um codigo, o eixo e a familia a que pertence, e a avaliacao.

    `axis` e `family` decidem como a pontuacao se combina com a das outras
    regras (ver controllers/engine/decision.py): dentro da mesma familia so
    a maior contribuicao conta.
    """

    code = ""
    axis = None
    family = None

    def evaluate(self, ctx, params: dict) -> RuleResult:
        raise NotImplementedError

    def triggered(self, points: int, detail: str, floor: str = NONE, hard_block: bool = False,
                  data_origin: str = "payload", evidence_ids: list = None, **extra) -> RuleResult:
        return RuleResult(
            rule=self.code, evaluation=TRIGGERED, axis=self.axis, family=self.family,
            raw_points=points, hard_block=hard_block, floor=floor, detail=detail,
            data_origin=data_origin, evidence_ids=evidence_ids or [], extra=extra,
        )

    def not_triggered(self, detail: str = "", **extra) -> RuleResult:
        return RuleResult(rule=self.code, evaluation=NOT_TRIGGERED, axis=self.axis, family=self.family,
                          detail=detail, extra=extra)

    def not_evaluable(self, detail: str, **extra) -> RuleResult:
        return RuleResult(rule=self.code, evaluation=NOT_EVALUABLE, axis=self.axis, family=self.family,
                          detail=detail, extra=extra)
