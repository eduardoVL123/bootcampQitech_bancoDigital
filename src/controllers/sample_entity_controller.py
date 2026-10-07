from datetime import date

from controllers.base_controller import BaseController
from dtos import SampleEntityDTO
from errors import (
    DuplicatedDocumentNumber,
    DuplicatedEmail,
    InvalidBirthdate,
    InvalidDocumentNumber,
    InvalidParameter,
    NotFoundSampleEntity,
    SampleEntityFinalStatus,
    UnderageSampleEntity,
)
from models import SampleEntity, SampleEntityStatus
from repositories import SampleEntityRepository
from utils.document_number import is_valid_cpf

# A faixa de idade aceita. Abaixo do mínimo o cadastro é RECUSADO; acima
# do máximo ele é CRIADO, mas já em "failed" — são desfechos diferentes,
# e o create lá embaixo mostra a diferença em duas linhas.
MINIMUM_AGE = 18
MAXIMUM_AGE = 80


class SampleEntityController(BaseController):
    """As regras de negócio. Aqui mora o "pode" e o "não pode"."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.sample_entity_repository = SampleEntityRepository(self.context)

    def create(self, sample_entity_data: dict) -> dict:
        """Confere quem está entrando, e só então cria.

        As quatro perguntas abaixo acontecem ANTES de qualquer escrita, e
        essa ordem é a regra: uma recusa não pode deixar meia entidade no
        banco. Repare que nenhuma delas é sobre FORMATO — isso o schema
        já cobrou lá na porta. Aqui é sobre o que só se sabe olhando o
        mundo: se o número existe, se alguém já usou, que idade a pessoa
        tem hoje.
        """
        self.logger.debug("Criando uma nova Sample Entity")

        document_number = sample_entity_data["document_number"]
        email = sample_entity_data["email"]
        birthdate = self._parse_birthdate(sample_entity_data["birthdate"])

        if not is_valid_cpf(document_number):
            raise InvalidDocumentNumber(document_number)

        if self.sample_entity_repository.get_by_document_number(document_number) is not None:
            raise DuplicatedDocumentNumber(document_number)

        if self.sample_entity_repository.get_by_email(email) is not None:
            raise DuplicatedEmail(email)

        age = self._age_in_years(birthdate)

        if age < MINIMUM_AGE:
            raise UnderageSampleEntity(age, MINIMUM_AGE)

        sample_entity = self.sample_entity_repository.create(sample_entity_data=sample_entity_data)

        # Passar da idade máxima não impede o cadastro: ele nasce em
        # "failed". É a diferença entre recusar o pedido e aceitá-lo com
        # outro desfecho — e as duas regras moram lado a lado de
        # propósito, pra que a diferença fique à vista.
        if age > MAXIMUM_AGE:
            new_status = SampleEntityStatus.FAILED
        else:
            new_status = SampleEntityStatus.PENDING

        self.sample_entity_repository.update_status(sample_entity, new_status)

        sample_entity_dto = SampleEntityDTO.only_obj_key(sample_entity)
        self.session.commit()

        return sample_entity_dto

    def get_by_key(self, sample_entity_key: str) -> dict:
        self.logger.debug(f"Buscando a entidade de chave {sample_entity_key}")

        sample_entity = self.sample_entity_repository.get_by_key(sample_entity_key)

        if sample_entity is None:
            raise NotFoundSampleEntity(sample_entity_key)

        return SampleEntityDTO.obj_to_dict(sample_entity)

    def get_list(self, limit: int, offset: int, filters: dict) -> dict:
        """A pagina pedida, depois de conferir se o pedido faz sentido.

        Um intervalo de nascimento de cabeca pra baixo — comeco depois
        do fim — nunca pode achar ninguem. Devolver zero linhas nesse
        caso mente por omissao: parece que a busca rodou e nao
        encontrou, quando na verdade a pergunta e que nao tinha
        resposta possivel.

        Quem decide que um pedido nao pode ser respondido e este
        controller. O resource fala HTTP, nao julga pedido.

        Repare no que NAO esta mais aqui: a lista de status validos.
        Aquilo era conferir se um valor pertence a um conjunto fixo —
        exatamente o que um `enum` de JSON Schema faz, e agora faz, no
        src/schemas/get_sample_entities.json. O que sobrou e o que
        nenhum schema sabe fazer: comparar dois campos ENTRE SI.
        """
        birthdate_from = filters.get("birthdate_from")
        birthdate_to = filters.get("birthdate_to")

        if birthdate_from is not None:
            birthdate_from = self._parse_birthdate(birthdate_from)
            filters["birthdate_from"] = birthdate_from

        if birthdate_to is not None:
            birthdate_to = self._parse_birthdate(birthdate_to)
            filters["birthdate_to"] = birthdate_to

        if birthdate_from is not None and birthdate_to is not None:
            if birthdate_from > birthdate_to:
                raise InvalidParameter(
                    f"birthdate_from ({birthdate_from}) is after birthdate_to ({birthdate_to})"
                )

        sample_entities_list = self.sample_entity_repository.list_page(limit, offset, filters)

        # Pedimos um a mais que o limite só pra saber se existe próxima
        # página. Se veio o extra, ele não entra na resposta.
        is_last_page = True
        if len(sample_entities_list) > limit:
            is_last_page = False
            sample_entities_list = sample_entities_list[:-1]

        return {
            "sample_entities_list_dto": SampleEntityDTO.list_obj_to_list_dict(sample_entities_list),
            "is_last_page": is_last_page,
        }

    def update_status(self, sample_entity_key: str, new_status: str) -> dict:
        sample_entity = self.sample_entity_repository.get_by_key(sample_entity_key)

        if sample_entity is None:
            raise NotFoundSampleEntity(sample_entity_key)

        self._check_status_can_change(sample_entity, new_status)

        self.sample_entity_repository.update_status(sample_entity, new_status)

        sample_entity_dto = SampleEntityDTO.only_obj_key(sample_entity)
        self.session.commit()

        return sample_entity_dto

    def webhook_increment_counter(self, sample_entity_key: str) -> None:
        self.logger.debug(f"Processando webhook da entidade {sample_entity_key}")

        sample_entity = self.sample_entity_repository.get_by_key(sample_entity_key)

        if sample_entity is None:
            raise NotFoundSampleEntity(sample_entity_key)

        self.sample_entity_repository.increment_counter(sample_entity)

        self.session.commit()

    def _check_status_can_change(self, sample_entity: SampleEntity, new_status: str) -> None:
        old_status = sample_entity.status.enumerator

        if old_status != SampleEntityStatus.PENDING:
            raise SampleEntityFinalStatus(old_status, new_status)

    def _parse_birthdate(self, raw_birthdate: str) -> date:
        """Converte a data, ou recusa com 422 em vez de 500.

        O schema já garantiu o FORMATO (quatro dígitos, traço, dois,
        traço, dois). O que ele não sabe é quantos dias fevereiro tem —
        um `pattern` conta caracteres, não consulta calendário. Por isso
        "2025-02-30" chega aqui intacto, e é aqui que ele para.
        """
        try:
            return date.fromisoformat(raw_birthdate)
        except ValueError:
            raise InvalidBirthdate(raw_birthdate)

    def _age_in_years(self, birthdate: date) -> int:
        today = date.today()
        age = today.year - birthdate.year

        # Quem ainda não fez aniversário este ano tem um ano a menos do
        # que a subtração acima diz.
        if (today.month, today.day) < (birthdate.month, birthdate.day):
            age = age - 1

        return age
