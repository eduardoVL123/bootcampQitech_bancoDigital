#!/usr/bin/env bash
# Gera o .docx da RFC 02 a partir do markdown, com os diagramas renderizados.
# O markdown e a fonte: edite 02-conta.md e rode este script de novo.
#
#   bash docs/rfc/gerar-docx.sh
#
# Precisa de: pandoc, npx (para o mermaid-cli) e ImageMagick.
set -euo pipefail
cd "$(dirname "$0")"
MD=02-conta.md
OUT="RFC 02 - API de conta e transacao.docx"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 1. Tira cada bloco mermaid do markdown e renderiza em PNG.
python3 - "$MD" "$TMP" <<'PY'
import re, sys
md, tmp = sys.argv[1], sys.argv[2]
for i, b in enumerate(re.findall(r'```mermaid\n(.*?)```', open(md, encoding='utf-8').read(), re.S), 1):
    open(f"{tmp}/d{i}.mmd", "w").write(b)
PY
for f in "$TMP"/*.mmd; do
  npx -y -q @mermaid-js/mermaid-cli -i "$f" -o "${f%.mmd}.png" -b white -s 2 >/dev/null 2>&1
done

# 2. Troca os blocos mermaid pelas imagens, com largura que cabe na pagina A4.
python3 - "$MD" "$TMP" <<'PY'
import re, subprocess, sys
md, tmp = sys.argv[1], sys.argv[2]
s = open(md, encoding='utf-8').read()
n = [0]
def repl(_):
    n[0] += 1
    w, h = map(int, subprocess.run(
        ["identify", "-format", "%w %h", f"{tmp}/d{n[0]}.png"],
        capture_output=True, text=True).stdout.split())
    # 17 cm de largura util, 22 cm de altura util, com margem de 1,8 cm
    cm = min(17.0, 22.0 / (h / w))
    return "![](%s/d%d.png){width=%.1fcm}" % (tmp, n[0], cm)
open(f"{tmp}/doc.md", "w", encoding='utf-8').write(re.sub(r'```mermaid\n.*?```', repl, s, flags=re.S))
PY

# 3. Converte. O reference.docx traz margem de 1,8 cm e tabela em 8,5 pt;
#    o --columns=40 e o que faz o pandoc respeitar a largura das colunas
#    escrita nos tracos do separador de cada tabela.
pandoc "$TMP/doc.md" \
  --from=gfm --reference-doc=.build/reference.docx --resource-path="$TMP" \
  --toc --toc-depth=2 --columns=40 \
  --metadata title="RFC 02: a API de conta e transacao, onde o dinheiro mora" \
  -o "$OUT"
echo "gerado: $OUT"

# 5. O PDF, que e o formato da entrega. O LibreOffice converte o .docx
#    ja montado, em vez de o pandoc gerar um PDF por outro caminho:
#    assim o que a banca le em PDF e exatamente o que esta no .docx.
if command -v libreoffice >/dev/null 2>&1; then
  libreoffice --headless --convert-to pdf "$OUT" --outdir . >/dev/null 2>&1
  echo "gerado: ${OUT%.docx}.pdf"
else
  echo "aviso: libreoffice nao encontrado, o PDF nao foi gerado"
fi
