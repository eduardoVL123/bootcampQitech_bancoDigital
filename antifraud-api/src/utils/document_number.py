CPF_LENGTH = 11
CNPJ_LENGTH = 14

CHECK_DIGIT_POSITIONS = [9, 10]

# Pesos do CNPJ: um para cada um dos 12 primeiros dígitos (primeiro
# verificador) e um para os 13 primeiros (segundo verificador).
CNPJ_FIRST_WEIGHTS = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ_SECOND_WEIGHTS = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def cnpj_values(document_number: str) -> list:
    """Cada caractere do CNPJ vira o número que entra na conta do verificador.

    Desde julho de 2026 a Receita emite CNPJ alfanumérico (IN RFB 2.229/2024):
    as 12 primeiras posições podem ter letras, as 2 últimas continuam
    dígitos, e a conta continua sendo o módulo 11. Cada caractere vale o
    seu código ASCII menos 48: "7" continua 7, "A" vale 17, "B" 18...
    Para um CNPJ só de números, nada muda.
    """
    return [ord(character) - 48 for character in normalize_document(document_number)]


def is_valid_cnpj(document_number: str) -> bool:
    """Diz se um CNPJ existe, pela mesma ideia do CPF: os dois últimos
    dígitos são o resultado de uma conta sobre os anteriores.

    Para cada verificador: multiplica cada dígito pelo peso da lista, soma,
    tira o resto da divisão por 11. Resto menor que 2 vira 0; nos outros
    casos, o dígito é 11 menos o resto. Dígitos todos iguais não valem.
    Vale também para o CNPJ alfanumérico (ver cnpj_values).
    """
    normalizado = normalize_document(document_number)
    digits = cnpj_values(normalizado)

    if len(digits) != CNPJ_LENGTH or len(set(digits)) == 1 or not normalizado[-2:].isdigit():
        return False

    for weights in [CNPJ_FIRST_WEIGHTS, CNPJ_SECOND_WEIGHTS]:
        position = len(weights)
        total = 0
        for index, weight in enumerate(weights):
            total = total + digits[index] * weight

        remainder = total % 11
        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True


def is_valid_cpf(document_number: str) -> bool:
    """Diz se um CPF existe de verdade — não se ele tem a cara certa.

    O schema em src/schemas/post_onboarding.json já cobrou o formato:
    três pontos, um hífen, onze dígitos. Isto aqui é outra pergunta, e a
    diferença entre as duas é a lição deste arquivo.

    Os dois últimos dígitos de um CPF não são escolhidos: eles são o
    RESULTADO de uma conta feita sobre os nove primeiros. Por isso um
    número pode ter o formato perfeito e não existir — "111.222.333-44"
    passa no schema e não passa aqui.

    É o mesmo motivo pelo qual a resposta dessa recusa é 422 e não 400:
    não é que a API não conseguiu ler o pedido; ela leu, entendeu, e o
    valor não pode existir.

    A conta, para cada um dos dois dígitos: multiplica cada dígito
    anterior por um peso que decresce, soma tudo, tira o resto da divisão
    por 11. Resto menor que 2 vira dígito 0; nos outros casos, o dígito é
    11 menos o resto.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(int(character))

    if len(digits) != CPF_LENGTH:
        return False

    # Um CPF de dígitos todos iguais ("111.111.111-11") passa na conta
    # dos dígitos verificadores e mesmo assim não vale. São onze números
    # conhecidos, e a Receita não emite nenhum deles.
    all_digits_are_equal = True
    for digit in digits:
        if digit != digits[0]:
            all_digits_are_equal = False
            break

    if all_digits_are_equal:
        return False

    for position in CHECK_DIGIT_POSITIONS:
        total = 0
        first_weight = position + 1

        for index in range(position):
            total = total + digits[index] * (first_weight - index)

        remainder = total % 11

        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True


def normalize_document(document_number: str) -> str:
    """O documento sem mascara, preservando zeros a esquerda e as letras.

    "123.456.789-09" e "12345678909" sao a mesma pessoa: o motor compara e
    grava sempre esta forma. Letras ficam (em maiuscula) por causa do CNPJ
    alfanumerico: tirar so os digitos de "12.ABC.345/01DE-35" deixaria
    "1234501" + "35", e duas empresas diferentes virariam o mesmo documento.
    """
    return "".join(character for character in document_number.upper() if character.isascii() and character.isalnum())


def is_legal_person(document_number: str) -> bool:
    return len(normalize_document(document_number)) == CNPJ_LENGTH


def has_valid_check_digits(document_number: str) -> bool:
    if is_legal_person(document_number):
        return is_valid_cnpj(document_number)
    return is_valid_cpf(document_number)
