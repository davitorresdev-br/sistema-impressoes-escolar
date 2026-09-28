#!/usr/bin/env bash
# Instalação do SERVIDOR do Sistema de Impressão numa VM Ubuntu.
#
#   sudo bash deploy/ubuntu/instalar.sh
#
# Pode rodar de novo quantas vezes quiser: nada é sobrescrito à toa, e o
# .env existente NUNCA é tocado (é onde moram as chaves).
#
# O que este script NÃO faz, de propósito:
#   * copiar o banco de dados     -> ver docs/MIGRACAO-UBUNTU.md (passo 4)
#   * gerar/rotacionar as chaves  -> idem (passo 3), é decisão com impacto
#   * configurar o agente Windows -> idem (passo 7)
# São passos que mexem em dados reais e merecem alguém olhando.

set -euo pipefail

DESTINO="${ACALANTO_DESTINO:-/opt/acalanto}"
USUARIO="${ACALANTO_USUARIO:-acalanto}"
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# COM ou SEM nginx. O sistema NÃO depende dele: o waitress abre a porta e
# serve a tela e a API sozinho. O nginx entra só para HTTPS e para deixar a
# aplicação fora do alcance direto da rede.
#
#   COM_NGINX=sim  (padrão) -> nginx na porta 80, aplicação em 127.0.0.1:8080
#   COM_NGINX=nao           -> aplicação direto na rede, sem proxy nenhum
#
# Para instalar sem nginx:  sudo COM_NGINX=nao bash instalar.sh
COM_NGINX="${COM_NGINX:-sim}"
# Porta usada quando NÃO há nginx. 8080 é o padrão (endereço fica
# "http://192.168.0.50:8080"); 80 deixa o endereço limpo, mas exige a
# permissão de porta baixa configurada abaixo.
PORTA_DIRETA="${ACALANTO_PORT:-8080}"

if [[ $EUID -ne 0 ]]; then
    echo "Rode com sudo: sudo bash $0" >&2
    exit 1
fi

echo "==> Origem:  $ORIGEM"
echo "==> Destino: $DESTINO"
echo

# ---------------------------------------------------------------- pacotes
echo "==> Instalando pacotes do sistema"
apt-get update -qq
# tzdata é obrigatório: o sistema usa o fuso America/Sao_Paulo (zoneinfo).
# Sem ele, TODO horário quebra — inclusive a janela de impressão.
apt-get install -y -qq python3 python3-venv python3-pip sqlite3 tzdata rsync
if [[ "$COM_NGINX" == "sim" ]]; then
    apt-get install -y -qq nginx
else
    echo "    (sem nginx, a pedido — a aplicação vai atender direto)"
fi

echo "==> Conferindo a versão do Python"
python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit(f"Python {sys.version.split()[0]} é antigo demais (o projeto usa zoneinfo, 3.9+).")
print(f"    Python {sys.version.split()[0]} OK")
PY

echo "==> Conferindo o fuso America/Sao_Paulo"
python3 - <<'PY'
from zoneinfo import ZoneInfo
from datetime import datetime
print("    agora em São Paulo:", datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds"))
PY

# ---------------------------------------------------------------- usuário
if ! id -u "$USUARIO" >/dev/null 2>&1; then
    echo "==> Criando o usuário de sistema '$USUARIO' (sem shell, sem home)"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$USUARIO"
else
    echo "==> Usuário '$USUARIO' já existe"
fi

# ---------------------------------------------------------------- arquivos
echo "==> Copiando a aplicação para $DESTINO"
mkdir -p "$DESTINO" "$DESTINO/logs" "$DESTINO/banco_dados"
# --exclude: o .env e o banco são de cada máquina; .venv e node_modules são
# recriados aqui; .git não tem por que ir para o servidor.
rsync -a --delete \
      --exclude '.git/' \
      --exclude '.venv/' \
      --exclude 'node_modules/' \
      --exclude '__pycache__/' \
      --exclude '.env' \
      --exclude 'agente.env' \
      --exclude 'banco_dados/*.db*' \
      --exclude 'logs/' \
      --exclude '*.log' \
      --exclude 'temp_impressao/' \
      "$ORIGEM/" "$DESTINO/"

# ---------------------------------------------------------------- venv
echo "==> Criando o ambiente virtual e instalando as dependências"
if [[ ! -x "$DESTINO/.venv/bin/python" ]]; then
    python3 -m venv "$DESTINO/.venv"
fi
"$DESTINO/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DESTINO/.venv/bin/python" -m pip install --quiet -r "$DESTINO/requirements.txt"

# ---------------------------------------------------------------- .env
if [[ ! -f "$DESTINO/.env" ]]; then
    echo "==> Criando .env a partir do exemplo (PRECISA ser preenchido)"
    cp "$DESTINO/.env.example" "$DESTINO/.env"
    {
        echo ""
        echo "# --- acrescentado pelo instalador da VM Ubuntu ---"
        if [[ "$COM_NGINX" == "sim" ]]; then
            echo "# Só o nginx fala com a aplicação; a porta 8080 não fica exposta."
            echo "ACALANTO_HOST=127.0.0.1"
            echo "ACALANTO_PORT=8080"
            echo "# Faz o sistema enxergar o IP real de quem acessa (via nginx)."
            echo "# Sem isto, o limite de tentativas de login trancaria todo mundo junto."
            echo "ACALANTO_ATRAS_DE_PROXY=true"
        else
            echo "# Sem proxy: a aplicação atende a rede diretamente."
            echo "ACALANTO_HOST=0.0.0.0"
            echo "ACALANTO_PORT=$PORTA_DIRETA"
            echo "# NÃO ligue ACALANTO_ATRAS_DE_PROXY sem um proxy na frente:"
            echo "# qualquer cliente poderia forjar o próprio IP e escapar do"
            echo "# limite de tentativas de login."
        fi
        echo "ACALANTO_LOG=$DESTINO/logs/servidor.log"
    } >> "$DESTINO/.env"
    echo "    !! Preencha ACALANTO_SECRET_KEY e AGENTE_API_KEY em $DESTINO/.env"
else
    echo "==> .env já existe — preservado (não foi tocado)"
fi

# ---------------------------------------------------------------- permissões
echo "==> Ajustando dono e permissões"
chown -R "$USUARIO:$USUARIO" "$DESTINO"
# O .env tem as chaves: só o dono lê.
chmod 600 "$DESTINO/.env"
chmod 700 "$DESTINO/banco_dados"
chmod +x "$DESTINO/deploy/ubuntu/backup-banco.sh"
mkdir -p /var/backups/acalanto
chown "$USUARIO:$USUARIO" /var/backups/acalanto

# ---------------------------------------------------------------- serviços
echo "==> Instalando os serviços do systemd"
cp "$DESTINO/deploy/ubuntu/acalanto.service"        /etc/systemd/system/
cp "$DESTINO/deploy/ubuntu/acalanto-backup.service" /etc/systemd/system/
cp "$DESTINO/deploy/ubuntu/acalanto-backup.timer"   /etc/systemd/system/
systemctl daemon-reload

if [[ "$COM_NGINX" == "sim" ]]; then
    echo "==> Configurando o nginx"
    cp "$DESTINO/deploy/ubuntu/nginx-acalanto.conf" /etc/nginx/sites-available/acalanto
    ln -sf /etc/nginx/sites-available/acalanto /etc/nginx/sites-enabled/acalanto
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
elif [[ "$PORTA_DIRETA" -lt 1024 ]]; then
    # Porta abaixo de 1024 é privilegiada: um serviço que não roda como root
    # não consegue abri-la. Esta capacidade concede só isso — bem menos que
    # rodar o serviço inteiro como root.
    echo "==> Liberando a porta $PORTA_DIRETA para o serviço (CAP_NET_BIND_SERVICE)"
    mkdir -p /etc/systemd/system/acalanto.service.d
    cat > /etc/systemd/system/acalanto.service.d/porta-baixa.conf <<EOF
[Service]
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
EOF
    systemctl daemon-reload
fi

echo
echo "======================================================================"
echo "Instalação concluída. FALTAM os passos que mexem em dados reais:"
echo
echo "  1. Preencher as chaves em $DESTINO/.env"
echo "       ACALANTO_SECRET_KEY e AGENTE_API_KEY"
echo "       (gere com: python3 -c \"import secrets; print(secrets.token_hex(32))\")"
echo
echo "  2. Copiar o banco para $DESTINO/banco_dados/acalanto_print.db"
echo "       e conferir com: $DESTINO/.venv/bin/python $DESTINO/deploy/conferir_banco.py"
echo
echo "  3. Subir tudo:"
echo "       sudo systemctl enable --now acalanto"
echo "       sudo systemctl enable --now acalanto-backup.timer"
if [[ "$COM_NGINX" == "sim" ]]; then
    echo "       sudo systemctl reload nginx"
    echo "     Endereço: http://impressao.exemplo.com.br/"
else
    echo "     Endereço: http://192.168.0.50:$PORTA_DIRETA/  (sem nginx)"
fi
echo
echo "  4. No PC da impressora, apontar o agente para esta VM (agente.env):"
echo "       CLOUD_URL=http://<ip-desta-vm>"
echo "       AGENTE_API_KEY=<a mesma chave do passo 1>"
echo
echo "Roteiro completo: docs/MIGRACAO-UBUNTU.md"
echo "======================================================================"
