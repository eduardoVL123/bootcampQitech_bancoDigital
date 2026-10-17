from sqlalchemy import text

from database import Context


class CompanyRegistryRepository:
    """O mock do cadastro de empresas: o CPF responsavel por cada CNPJ.

    Fornece o vinculo; quem decide e o motor (controllers/rules/contas_novas_do_grupo.py).
    Uma linha vale enquanto o CNPJ esta em aberto no nome daquele CPF.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def links_of_cnpj(self, cnpj: str) -> list:
        return self.session.execute(text(
            "SELECT cnpj, responsible_cpf, evidence_id, available_from, expires_at, fixture_version "
            "FROM company_registry_fixture WHERE cnpj = :cnpj ORDER BY available_from"
        ), {"cnpj": cnpj}).all()

    def open_cnpjs_of(self, cpf: str, moment) -> list:
        """Os CNPJs em aberto deste CPF no instante do Pix."""
        return self.session.execute(text(
            "SELECT cnpj, evidence_id, fixture_version FROM company_registry_fixture "
            "WHERE responsible_cpf = :cpf AND available_from <= :momento AND expires_at > :momento ORDER BY cnpj"
        ), {"cpf": cpf, "momento": moment}).all()
