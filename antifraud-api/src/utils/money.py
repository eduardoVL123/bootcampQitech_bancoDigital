def brl(cents: int) -> str:
    """Centavos para o texto que uma pessoa le: 150000 -> "R$ 1.500,00"."""
    reais, centavos = divmod(abs(int(cents)), 100)
    inteiro = f"{reais:,}".replace(",", ".")
    sinal = "-" if cents < 0 else ""
    return f"{sinal}R$ {inteiro},{centavos:02d}"
