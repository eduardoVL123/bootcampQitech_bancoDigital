# O worker que entrega os webhooks. O contexto de build e a raiz do
# repositorio, e nao esta pasta: assim o pacote webhook_api entra na
# imagem com o caminho dele inteiro, e os imports
# "webhook_api.src.alguma_coisa" funcionam igual aqui e na sua maquina.
FROM python:3.11-slim AS base

RUN adduser --system --no-create-home user

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt /requirements.txt
RUN pip install --upgrade pip && pip install -r /requirements.txt

WORKDIR /app
COPY webhook_api /app/webhook_api

FROM base AS worker
RUN chown -R user /app
USER user

CMD ["python", "-m", "webhook_api.src.worker"]
