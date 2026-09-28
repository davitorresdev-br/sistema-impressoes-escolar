#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup do banco COM O SERVIDOR NO AR.

Usa a API de backup do próprio SQLite (`Connection.backup`), e não uma
cópia de arquivo: desde que o WAL foi ligado, o banco são três arquivos
(.db, .db-wal, .db-shm) e copiar só o .db pode deixar de fora as últimas
transações — inclusive os pedidos da manhã. Esta API faz a cópia de forma
consistente, sem parar o serviço.

É Python puro da biblioteca padrão, então roda igual no Windows e no Linux
e não depende do sqlite3.exe estar instalado.

Uso:
    python backup_banco.py                      # caminhos padrão
    python backup_banco.py <banco> <destino>    # explícito

Configurável pelo ambiente:
    ACALANTO_DB              caminho do banco
    ACALANTO_BACKUP_DIR      pasta de destino
    ACALANTO_BACKUP_MANTER   dias de retenção (padrão 14)
"""
import gzip
import io
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def caminho_banco():
    if len(sys.argv) > 1:
        return sys.argv[1]
    return os.environ.get("ACALANTO_DB") or os.path.join(
        RAIZ, "banco_dados", "acalanto_print.db")


def pasta_destino():
    if len(sys.argv) > 2:
        return sys.argv[2]
    return os.environ.get("ACALANTO_BACKUP_DIR") or os.path.join(RAIZ, "backups")


def main():
    banco = caminho_banco()
    destino = pasta_destino()
    manter_dias = int(os.environ.get("ACALANTO_BACKUP_MANTER", "14"))

    if not os.path.isfile(banco):
        print(f"ERRO: banco não encontrado em {banco}", file=sys.stderr)
        return 1

    os.makedirs(destino, exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M")
    bruto = os.path.join(destino, f"acalanto_print_{carimbo}.db")

    # Backup a quente: o servidor pode estar atendendo normalmente.
    origem = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    copia = sqlite3.connect(bruto)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()

    # Um backup que não abre não é backup: conferimos ANTES de apagar os
    # antigos, e abortamos se a cópia estiver ruim.
    conferencia = sqlite3.connect(f"file:{bruto}?mode=ro", uri=True)
    try:
        integridade = conferencia.execute("PRAGMA integrity_check;").fetchone()[0]
        pedidos = conferencia.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
        usuarios = conferencia.execute("SELECT COUNT(*) FROM usuarios_locais").fetchone()[0]
    finally:
        conferencia.close()

    if integridade != "ok":
        print(f"ERRO: a cópia não passou no integrity_check ({integridade}) — "
              "mantendo os backups antigos.", file=sys.stderr)
        os.remove(bruto)
        return 2

    with open(bruto, "rb") as entrada, gzip.open(bruto + ".gz", "wb") as saida:
        shutil.copyfileobj(entrada, saida)

    # A cópia herda o modo WAL da origem, e a conexão de conferência é somente
    # leitura — não pode consolidar nem apagar o WAL ao fechar. Sem esta
    # limpeza sobram um .db-wal e um .db-shm por execução, que a rotação
    # abaixo não recolhe (ela só olha *.db.gz) e se acumulam para sempre.
    for sufixo in ("", "-wal", "-shm"):
        try:
            os.remove(bruto + sufixo)
        except FileNotFoundError:
            pass

    tamanho = os.path.getsize(bruto + ".gz") / (1024 * 1024)
    print(f"Backup OK: {bruto}.gz ({tamanho:.1f} MB, {pedidos} pedidos, "
          f"{usuarios} usuários)")

    # Rotação por idade.
    corte = datetime.now() - timedelta(days=manter_dias)
    apagados = 0
    for nome in os.listdir(destino):
        if not (nome.startswith("acalanto_print_") and nome.endswith(".db.gz")):
            continue
        caminho = os.path.join(destino, nome)
        if datetime.fromtimestamp(os.path.getmtime(caminho)) < corte:
            os.remove(caminho)
            apagados += 1

    restantes = sum(1 for n in os.listdir(destino)
                    if n.startswith("acalanto_print_") and n.endswith(".db.gz"))
    print(f"Backups mantidos: {restantes} (apagados {apagados}; política: {manter_dias} dias)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
