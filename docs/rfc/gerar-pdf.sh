#!/usr/bin/env bash
# Gera o .docx e o PDF de UMA RFC, a partir do markdown, com os
# diagramas mermaid ja renderizados em imagem.
#
#   bash docs/rfc/gerar-pdf.sh                      # todas as RFCs
#   bash docs/rfc/gerar-pdf.sh 02-conta.md          # so uma
#
# O markdown e a fonte: edite o .md e rode de novo. O .docx e o PDF
# nao vao para o git, justamente para nao existirem duas versoes da
# mesma coisa, uma delas desatualizada.
#
# Precisa de: pandoc, npx (para o mermaid-cli), ImageMagick e
# libreoffice. Sem o libreoffice sai so o .docx.
set -euo pipefail
cd "$(dirname "$0")"

# Onde cada RFC mora e como o arquivo gerado se chama. Duas estao na
# raiz do repositorio e duas aqui: enquanto o time nao decide um lugar
# so, o script sabe os dois.
declare -A RFCS=(
  ["02-conta.md"]="RFC 02 - API de conta e transacao"
  ["05-onboarding-api.md"]="RFC 05 - API de abertura de conta"
  ["../../RFC 01 - API de Cliente.md"]="RFC 01 - API de Cliente"
  ["../../RFC 06 - API de Webhooks Outgoing.md"]="RFC 06 - API de Webhooks Outgoing"
)

gera() {
  local MD="$1"
  local OUT="$2.docx"

  if [ ! -f "$MD" ]; then
    echo "pulei: $MD nao existe"
    return
  fi

  local TMP
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' RETURN

  # 1. Tira cada bloco mermaid do markdown e renderiza em PNG.
  python3 - "$MD" "$TMP" <<'PY'
import re, sys
md, tmp = sys.argv[1], sys.argv[2]
for i, b in enumerate(re.findall(r'```mermaid\n(.*?)```', open(md, encoding='utf-8').read(), re.S), 1):
    open(f"{tmp}/d{i}.mmd", "w").write(b)
PY
  shopt -s nullglob
  for f in "$TMP"/*.mmd; do
    npx -y -q @mermaid-js/mermaid-cli -i "$f" -o "${f%.mmd}.png" -b white -s 2 >/dev/null 2>&1
  done
  shopt -u nullglob

  # 2. Troca os blocos mermaid pelas imagens, com largura que cabe na A4.
  python3 - "$MD" "$TMP" <<'PY'
import os, re, subprocess, sys
md, tmp = sys.argv[1], sys.argv[2]
s = open(md, encoding='utf-8').read()
n = [0]
def repl(bloco):
    n[0] += 1
    png = f"{tmp}/d{n[0]}.png"
    if not os.path.exists(png):
        # O mermaid nao conseguiu desenhar este: deixa o codigo do
        # diagrama no lugar, em vez de sumir com ele em silencio.
        return "```\n" + bloco.group(0).split("\n", 1)[1]
    w, h = map(int, subprocess.run(
        ["identify", "-format", "%w %h", png],
        capture_output=True, text=True).stdout.split())
    # 17 cm de largura util, 22 cm de altura util, margem de 1,8 cm
    cm = min(17.0, 22.0 / (h / w))
    return "![](%s){width=%.1fcm}" % (png, cm)
open(f"{tmp}/doc.md", "w", encoding='utf-8').write(re.sub(r'```mermaid\n.*?```', repl, s, flags=re.S))
PY

  # 3. O titulo da capa sai do primeiro "# " do proprio markdown.
  local TITULO
  TITULO=$(grep -m1 '^# ' "$MD" | sed 's/^# //')

  # 4. Converte. O reference.docx traz margem de 1,8 cm e tabela em
  #    8,5 pt; o --columns=40 e o que faz o pandoc respeitar a largura
  #    das colunas escrita nos tracos do separador de cada tabela.
  pandoc "$TMP/doc.md" \
    --from=gfm --reference-doc=.build/reference.docx --resource-path="$TMP" \
    --toc --toc-depth=2 --columns=40 \
    --metadata title="$TITULO" \
    -o "$OUT"
  echo "gerado: $OUT"

  # 5. O PDF, que e o formato da entrega. O LibreOffice converte o
  #    .docx ja montado, em vez de o pandoc gerar um PDF por outro
  #    caminho: assim o que a banca le em PDF e exatamente o .docx.
  if command -v libreoffice >/dev/null 2>&1; then
    libreoffice --headless --convert-to pdf "$OUT" --outdir . >/dev/null 2>&1
    echo "gerado: ${OUT%.docx}.pdf"
  else
    echo "aviso: libreoffice nao encontrado, o PDF nao foi gerado"
  fi
}

if [ $# -gt 0 ]; then
  for md in "$@"; do
    gera "$md" "${RFCS[$md]:-${md%.md}}"
  done
else
  for md in "${!RFCS[@]}"; do
    gera "$md" "${RFCS[$md]}"
  done
fi
