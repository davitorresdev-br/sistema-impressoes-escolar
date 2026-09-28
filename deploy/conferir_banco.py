#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radiografia do banco, para comparar ANTES e DEPOIS da migração.

Rode na máquina de origem e na VM de destino e compare as duas saídas: se
bater tudo, nada se perdeu no caminho. É a diferença entre "copiei o
arquivo" e "sei que o arquivo chegou inteiro".

Serve para as duas migrações (Ubuntu e Windows) — é Python puro da
biblioteca padrão, por isso mora em deploy/ e não numa das duas pastas.

Uso:
    python conferir_banco.py                        # caminho padrão
    python conferir_banco.py /caminho/para/db       # caminho explícito

Abre o banco SOMENTE LEITURA — pode rodar com o servidor no ar.
"""
import hashlib
import io
import os
import sqlite3
import sys

# O console do Windows não usa UTF-8 por padrão, e a saída sairia com
# acentos quebrados — justo num relatório que existe para ser COMPARADO
# entre os dois lados. No Linux isto é inofensivo.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PADROES = [
    "/opt/acalanto/banco_dados/acalanto_print.db",   # VM Ubuntu
    r"C:\acalanto\banco_dados\acalanto_print.db",    # VM Windows
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "banco_dados", "acalanto_print.db"),
]


def achar_banco():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for caminho in PADROES:
        if os.path.isfile(caminho):
            return os.path.abspath(caminho)
    print("ERRO: banco não encontrado. Passe o caminho como argumento.", file=sys.stderr)
    sys.exit(1)


def main():
    caminho = achar_banco()
    print(f"Banco: {caminho}")
    print(f"Tamanho: {os.path.getsize(caminho) / (1024*1024):.1f} MB")

    # mode=ro: impossível escrever, mesmo por engano.
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    integridade = cur.execute("PRAGMA integrity_check;").fetchone()[0]
    print(f"\nintegrity_check: {integridade}")
    if integridade != "ok":
        print("*** BANCO COM PROBLEMA — não migre esta cópia. ***")

    print("\n=== contagens ===")
    for tabela in ("pedidos", "usuarios_locais", "usuarios_workspace", "eventos"):
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            print(f"  {tabela:<20} {n}")
        except sqlite3.Error as e:
            print(f"  {tabela:<20} (ausente: {e})")

    print("\n=== pedidos por status ===")
    for linha in cur.execute("SELECT status, COUNT(*) n FROM pedidos GROUP BY status ORDER BY status"):
        print(f"  {linha['status']:<12} {linha['n']}")

    # Somas que mudam se QUALQUER linha se perder ou truncar. É a conferência
    # que pega uma cópia incompleta que, por fora, parece inteira.
    print("\n=== somas de conferência ===")
    linha = cur.execute("""
        SELECT COALESCE(SUM(copias), 0)             AS copias,
               COALESCE(SUM(COALESCE(paginas, 0)), 0) AS paginas,
               COALESCE(SUM(COALESCE(folhas, 0)), 0)  AS folhas,
               COALESCE(MAX(id), 0)                  AS ultimo_id
          FROM pedidos
    """).fetchone()
    for campo in ("copias", "paginas", "folhas", "ultimo_id"):
        print(f"  {campo:<20} {linha[campo]}")

    # O hash dos hashes dos PDFs: prova que os arquivos são os mesmos, sem
    # precisar ler 185 MB de BLOB duas vezes.
    hashes = cur.execute(
        "SELECT arquivo_hash FROM pedidos WHERE arquivo_hash IS NOT NULL ORDER BY id"
    ).fetchall()
    digest = hashlib.sha256("".join(h[0] for h in hashes).encode()).hexdigest()
    print(f"  hash dos {len(hashes)} PDFs   {digest[:32]}…")

    # PDFs ainda guardados (a retenção pode ter descartado alguns).
    guardados = cur.execute(
        "SELECT COUNT(*) FROM pedidos WHERE arquivo_purgado = 0 AND arquivo_conteudo IS NOT NULL"
    ).fetchone()[0]
    print(f"  PDFs ainda no banco  {guardados}")

    print("\n=== contas por cargo ===")
    for linha in cur.execute("SELECT role, COUNT(*) n FROM usuarios_locais GROUP BY role ORDER BY role"):
        print(f"  {linha['role']:<14} {linha['n']}")

    conn.close()
    print("\nCompare esta saída com a do outro lado. Tudo igual = migração íntegra.")


if __name__ == "__main__":
    main()
