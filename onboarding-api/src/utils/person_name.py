import unicodedata


def normalize_name(name: str) -> str:
    """O nome do jeito que se compara com a Receita (decisão D13): sem acento,
    sem diferença de maiúscula e sem espaço sobrando. JOSÉ  DA SILVA e
    Jose da Silva viram o mesmo nome."""
    without_accents = "".join(
        letter for letter in unicodedata.normalize("NFKD", name) if not unicodedata.combining(letter)
    )
    return " ".join(without_accents.casefold().split())
