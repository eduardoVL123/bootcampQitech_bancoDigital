import functools
import json
import os

from jsonschema import Draft7Validator, RefResolver, validators

from constants import SCHEMA_PATH
from errors import InvalidSchema, MissingRequiredFields


# A regra de cada erro, com o vocabulário da RFC 05 (Formato de erro).
# O que não é obrigatório, tipo, mínimo ou máximo vira "format".
RULE_BY_VALIDATOR = {
    "required": "required",
    "type": "type",
    "minimum": "minimum",
    "exclusiveMinimum": "minimum",
    "minLength": "minimum",
    "minItems": "minimum",
    "maximum": "maximum",
    "exclusiveMaximum": "maximum",
    "maxLength": "maximum",
    "maxItems": "maximum",
}

# A mensagem nunca repete o valor recebido: o valor pode ser um CPF ou uma renda.
MESSAGE_BY_RULE = {
    "required": "Campo obrigatório.",
    "type": "Tipo inválido.",
    "minimum": "Abaixo do mínimo permitido.",
    "maximum": "Acima do máximo permitido.",
    "format": "Formato inválido.",
}

UNKNOWN_FIELD_MESSAGE = "Campo não aceito."


def is_strict_integer(checker, instance) -> bool:
    """Inteiro de verdade. O padrão do JSON Schema aceita 1000.0 como inteiro;
    aqui não, porque dinheiro nunca é float (R6)."""
    return isinstance(instance, int) and not isinstance(instance, bool)


StrictValidator = validators.extend(
    Draft7Validator,
    type_checker=Draft7Validator.TYPE_CHECKER.redefine("integer", is_strict_integer),
)


class SchemaCache:
    """Guarda os schemas já lidos do disco, para não reler a cada requisição."""

    schemas = {}

    @staticmethod
    def get_schema(schema_file_name: str) -> dict:
        schema_path = os.path.join(SCHEMA_PATH, schema_file_name)

        if schema_path in SchemaCache.schemas:
            return SchemaCache.schemas[schema_path]

        if not os.path.isfile(schema_path):
            raise Exception(
                f"Nao encontrei o schema '{schema_file_name}' em {SCHEMA_PATH}. "
                + "Ou o arquivo nao existe, ou o nome escrito na rota esta diferente."
            )

        with open(schema_path, "r", encoding="utf-8") as arquivo:
            schema = json.loads(arquivo.read())

        SchemaCache.schemas[schema_path] = schema

        return schema


class SchemaHandler:
    """Confere o corpo e a query string contra os arquivos de src/schemas/.

    Diferente da base, junta TODOS os problemas do pedido numa resposta só,
    para a pessoa corrigir tudo de uma vez:
      - se falta algum campo obrigatório, responde 400 ONB005001 listando
        cada campo ausente (decisão D12: o ausente vem antes do torto);
      - senão, responde 400 ONB000001 listando cada campo e a regra.
    """

    @staticmethod
    def validate(schema_file_name: str):
        """Decorator que valida o `payload` antes de o resource rodar."""

        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                if "payload" not in kwargs:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o SchemaHandler, mas nao "
                        + "tem um parametro chamado 'payload'. E de la que sai o corpo a validar."
                    )

                check_against_schema(kwargs["payload"], schema_file_name)

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate

    @staticmethod
    def validate_query_params(schema_file_name: str):
        """Decorator que valida a QUERY STRING antes de o resource rodar.

        O campo declarado como "type": "array" no schema vem por `getlist`;
        o resto vem simples. Parâmetro com nome errado cai no
        `additionalProperties: false` do schema.
        """

        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                request = kwargs.get("request")
                if request is None:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o validate_query_params, mas "
                        + "nao tem um parametro chamado 'request'. E de la que sai a query string."
                    )

                schema = SchemaCache.get_schema(schema_file_name)
                check_against_schema(query_params_to_dict(request.query_params, schema), schema_file_name)

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate


def check_against_schema(instance, schema_file_name: str) -> None:
    schema = SchemaCache.get_schema(schema_file_name)
    resolver = RefResolver(f"file://{SCHEMA_PATH}/", None)
    validator = StrictValidator(schema, resolver=resolver)

    errors = describe_errors(validator.iter_errors(instance))

    missing = [error for error in errors if error["rule"] == "required"]
    if missing:
        raise MissingRequiredFields(missing)

    if errors:
        raise InvalidSchema("The request has fields in an invalid format.", errors)


def describe_errors(schema_errors) -> list:
    """Traduz os erros do jsonschema em {field, rule, message}, sem repetir valores."""
    described = []

    for error in schema_errors:
        for field, rule, message in fields_of(error):
            item = {"field": field, "rule": rule, "message": message}
            if item not in described:
                described.append(item)

    described.sort(key=lambda item: (item["rule"] != "required", item["field"]))
    return described


def fields_of(error) -> list:
    """Diz quais campos o erro aponta. Três casos precisam de cuidado,
    porque o jsonschema aponta o objeto inteiro, e não o campo:
      - campo obrigatório ausente;
      - campo que não existe no schema (additionalProperties);
      - campo proibido para o tipo de cliente (subschema `false`)."""
    if error.validator == "required":
        missing = [name for name in error.validator_value if name not in error.instance]
        return [(name, "required", MESSAGE_BY_RULE["required"]) for name in missing]

    if error.validator == "additionalProperties":
        declared = error.schema.get("properties", {})
        unknown = [name for name in error.instance if name not in declared]
        return [(name, "format", UNKNOWN_FIELD_MESSAGE) for name in unknown]

    field = ".".join(str(part) for part in error.absolute_path) or "body"

    if error.validator is None:
        return [(field, "format", UNKNOWN_FIELD_MESSAGE)]

    rule = RULE_BY_VALIDATOR.get(error.validator, "format")
    return [(field, rule, MESSAGE_BY_RULE[rule])]


def query_params_to_dict(query_params, schema: dict) -> dict:
    """A query string virada dicionário, com o schema dizendo o que é lista.

    Campo ausente não entra: quem não veio não tem o que validar.
    """
    properties = schema.get("properties", {})
    parsed_params = {}

    for param_name in query_params.keys():
        declared = properties.get(param_name, {})

        if declared.get("type") == "array":
            parsed_params[param_name] = query_params.getlist(param_name)
        else:
            parsed_params[param_name] = query_params[param_name]

    return parsed_params
