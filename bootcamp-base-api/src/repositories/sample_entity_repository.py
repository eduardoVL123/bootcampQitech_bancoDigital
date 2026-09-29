from datetime import date, datetime
from uuid import uuid4

from database import Context
from models import SampleEntity, SampleEntityStatus, SampleEntityStatusEvent


class SampleEntityRepository:
    """A camada que fala com o banco. Só aqui existe query.

    Nenhuma regra de negócio mora aqui: esta classe busca, guarda e
    atualiza — quem decide o que fazer com isso é o controller.

    Repare no que ele recebe: o CONTEXTO do trabalho, e não a sessão
    solta. A sessão é o que ele tira de lá na linha seguinte, e é tudo de
    que precisa hoje — mas a assinatura já fala a língua do que viaja
    entre as camadas. No dia em que o contexto carregar também o
    identificador da requisição, nenhum construtor daqui até o resource
    muda de forma.

    É assim nos serviços da QI, e a linha é a mesma lá e aqui:
    `self.session = context.db_session`.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, sample_entity_data: dict) -> SampleEntity:
        sample_entity = SampleEntity()

        sample_entity.sample_entity_data = {"hello": sample_entity_data["hello"]}
        sample_entity.name = sample_entity_data["name"]
        sample_entity.email = sample_entity_data["email"]
        sample_entity.document_number = sample_entity_data["document_number"]
        sample_entity.birthdate = date.fromisoformat(sample_entity_data["birthdate"])
        sample_entity.sample_entity_key = str(uuid4())
        sample_entity.counter = 0
        sample_entity.status = self.get_status(SampleEntityStatus.CREATED)

        self.session.add(sample_entity)
        return sample_entity

    def update_status(self, sample_entity: SampleEntity, new_status_enumerator: str) -> None:
        new_status = self.get_status(new_status_enumerator)
        sample_entity.status = new_status

        new_status_event = SampleEntityStatusEvent()
        new_status_event.status = new_status
        new_status_event.event_datetime = datetime.now()

        sample_entity.status_events.append(new_status_event)

    def increment_counter(self, sample_entity: SampleEntity) -> None:
        sample_entity.counter = sample_entity.counter + 1

    def get_by_key(self, sample_entity_key: str) -> SampleEntity:
        return self.session.query(SampleEntity).filter(SampleEntity.sample_entity_key == sample_entity_key).first()

    def get_by_document_number(self, document_number: str) -> SampleEntity:
        return self.session.query(SampleEntity).filter(SampleEntity.document_number == document_number).first()

    def get_by_email(self, email: str) -> SampleEntity:
        return self.session.query(SampleEntity).filter(SampleEntity.email == email).first()

    def get_status(self, enumerator: str) -> SampleEntityStatus:
        return self.session.query(SampleEntityStatus).filter(SampleEntityStatus.enumerator == enumerator).one()

    def list_page(self, limit: int, offset: int, filters: dict) -> list:
        """A pagina, estreitada por quantos filtros vierem preenchidos.

        Todo filtro segue a mesma forma: veio vazio, nao entra na query;
        veio preenchido, vira mais um `.filter()`. Como cada um deles
        acrescenta uma condicao a MESMA query, eles se somam com E — dois
        filtros sempre devolvem menos linhas que um, nunca mais.

        Repare que `ilike` e diferente de `==`: o nome casa por pedaco e
        sem ligar pra maiuscula, enquanto e-mail e CPF exigem o valor
        inteiro e exato. Essa diferenca e decisao de produto, nao detalhe
        tecnico — quem procura uma pessoa lembra meio nome, mas quem
        procura um CPF tem o CPF.

        A ordenacao no fim nao e enfeite: `limit` e `offset` recortam
        um conjunto, e um conjunto sem ordem pode voltar do banco em
        qualquer sequencia. Sem o `order_by`, a pagina 2 tem permissao
        de repetir uma linha da pagina 1 e sumir com outra. O desempate
        por `id` existe porque duas entidades podem nascer no mesmo
        instante — e ai `created_at` sozinho ainda deixaria a ordem em
        aberto.
        """
        query = self.session.query(SampleEntity)

        status_enumerators = filters.get("status_enumerators")
        if status_enumerators:
            query = query.join(SampleEntity.status).filter(SampleEntityStatus.enumerator.in_(status_enumerators))

        name = filters.get("name")
        if name is not None:
            query = query.filter(SampleEntity.name.ilike(f"%{name}%"))

        email = filters.get("email")
        if email is not None:
            query = query.filter(SampleEntity.email == email)

        document_number = filters.get("document_number")
        if document_number is not None:
            query = query.filter(SampleEntity.document_number == document_number)

        birthdate_from = filters.get("birthdate_from")
        if birthdate_from is not None:
            query = query.filter(SampleEntity.birthdate >= birthdate_from)

        birthdate_to = filters.get("birthdate_to")
        if birthdate_to is not None:
            query = query.filter(SampleEntity.birthdate <= birthdate_to)

        query = query.order_by(SampleEntity.created_at.desc(), SampleEntity.id.desc())

        return query.limit(limit + 1).offset(offset).all()
