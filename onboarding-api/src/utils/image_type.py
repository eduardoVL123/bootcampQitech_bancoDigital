from typing import Optional


# A assinatura de cada formato: os primeiros bytes de todo arquivo dele.
JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def detect_image_type(content: bytes) -> Optional[str]:
    """O tipo da imagem pelos primeiros bytes (RFC 05, envio do RG).

    O nome do arquivo e o Content-Type são o que o cliente diz: um PDF
    chamado rg.jpg continua sendo um PDF. Devolve None se não é JPEG nem PNG.
    """
    if content.startswith(JPEG_SIGNATURE):
        return "image/jpeg"

    if content.startswith(PNG_SIGNATURE):
        return "image/png"

    return None
