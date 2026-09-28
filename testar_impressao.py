r"""
testar_impressao.py

Teste de bancada da impressão — NÃO passa pelo servidor, pelo banco nem pelo
horário de funcionamento do agente. Serve para responder uma pergunta só:
o driver da Konica está honrando as opções que mandamos no comando?

    # só mostra os comandos, não imprime nada
    .\.venv\Scripts\python.exe testar_impressao.py

    # imprime de verdade (gasta papel)
    .\.venv\Scripts\python.exe testar_impressao.py --imprimir

Gera um PDF de 4 páginas, cada uma com um bloco de cor diferente e o número
bem grande, e manda imprimir nas quatro combinações que importam. Depois é
olhar o papel:

  * O bloco saiu colorido no teste "Colorida"? -> a Konica honra dmColor.
  * O teste "Frente e Verso" saiu em 2 folhas (frente e verso)? -> honra dmDuplex.
  * O teste "Apenas Frente" saiu em 4 folhas soltas? -> o simplex explícito
    está vencendo o padrão TwoSidedLongEdge da fila de grampo.
  * O teste com grampo saiu grampeado?
"""

import os
import sys

from automacao_impressora import disparar_impressao_windows

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_impressao")
CAMINHO_PDF = os.path.join(PASTA, "_teste_impressao.pdf")

# (rótulo, cor, frente_verso, acabamento)
CASOS = [
    ("P&B, apenas frente", "PB", "Frente", "Normal"),
    ("Colorida, apenas frente", "Colorida", "Frente", "Normal"),
    ("P&B, frente e verso", "PB", "FrenteVerso", "Normal"),
    ("P&B, frente e verso, grampeada", "PB", "FrenteVerso", "Grampeada"),
]

# R, G, B (0-1) e nome do bloco de cada página.
PAGINAS = [
    ((1.0, 0.15, 0.15), "VERMELHO"),
    ((0.15, 0.35, 1.0), "AZUL"),
    ((0.10, 0.65, 0.25), "VERDE"),
    ((0.55, 0.55, 0.55), "CINZA"),
]


def _conteudo_pagina(numero, rgb, nome_cor):
    r, g, b = rgb
    return (
        f"{r:.2f} {g:.2f} {b:.2f} rg\n"
        f"57 500 481 220 re f\n"
        f"0 0 0 rg\n"
        f"BT /F1 90 Tf 57 380 Td (PAGINA {numero}) Tj ET\n"
        f"BT /F1 28 Tf 57 320 Td (Bloco acima deve estar {nome_cor}) Tj ET\n"
        f"BT /F1 20 Tf 57 270 Td (Se saiu cinza, a impressora ignorou o pedido de cor.) Tj ET\n"
    )


def gerar_pdf_de_teste(caminho):
    """
    Escreve um PDF A4 de 4 páginas sem depender de biblioteca externa.

    O agente não tem reportlab nem similar instalado, e não vale a pena
    acrescentar uma dependência só para o teste — o formato é simples o
    bastante para montar na mão, desde que os offsets da xref batam.
    """
    objetos = []

    def add(corpo):
        objetos.append(corpo)
        return len(objetos)  # número do objeto (1-based)

    # Reservamos os números na ordem em que serão referenciados.
    n_catalogo, n_paginas, n_fonte = 1, 2, 3
    objetos.extend([None, None, None])

    ids_paginas = []
    for i, (rgb, nome_cor) in enumerate(PAGINAS, start=1):
        fluxo = _conteudo_pagina(i, rgb, nome_cor).encode("latin-1")
        n_conteudo = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(fluxo), fluxo))
        n_pagina = add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (n_paginas, n_fonte, n_conteudo)
        )
        ids_paginas.append(n_pagina)

    objetos[n_catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % n_paginas
    objetos[n_paginas - 1] = b"<< /Type /Pages /Count %d /Kids [%s] >>" % (
        len(ids_paginas),
        b" ".join(b"%d 0 R" % i for i in ids_paginas),
    )
    objetos[n_fonte - 1] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for numero, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n" % numero + corpo + b"\nendobj\n"

    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n" % (len(objetos) + 1)
    saida += b"0000000000 65535 f \n"
    for deslocamento in offsets:
        saida += b"%010d 00000 n \n" % deslocamento
    saida += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objetos) + 1,
        n_catalogo,
        inicio_xref,
    )

    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "wb") as arquivo:
        arquivo.write(bytes(saida))


def main():
    imprimir_de_verdade = "--imprimir" in sys.argv

    gerar_pdf_de_teste(CAMINHO_PDF)
    print(f"PDF de teste: {CAMINHO_PDF} ({os.path.getsize(CAMINHO_PDF)} bytes, 4 páginas)\n")

    if not imprimir_de_verdade:
        print("MODO SECO — nada será impresso. Rode com --imprimir para valer.\n")

    for rotulo, cor, frente_verso, acabamento in CASOS:
        print("=" * 70)
        print(f"CASO: {rotulo}")
        if imprimir_de_verdade:
            sucesso, motivo = disparar_impressao_windows(
                "Teste de bancada", "Diagnóstico", "T.I.",
                CAMINHO_PDF, 1, cor, frente_verso, acabamento,
            )
            if not sucesso:
                # É a mesma frase que o professor veria na fila.
                print(f"  ⚠️ motivo relatado ao professor: {motivo}")
        else:
            from automacao_impressora import interpretar_opcoes, mapear_fila_impressora, montar_print_settings

            colorida, _grampeada, duplex = interpretar_opcoes(cor, acabamento, frente_verso)
            print(f"  fila            = {mapear_fila_impressora(cor, acabamento, frente_verso)}")
            print(f"  -print-settings = {montar_print_settings(colorida, duplex, 1)}")
        print()

    print("=" * 70)
    if imprimir_de_verdade:
        print("Confira o papel: cor no caso 'Colorida', 2 folhas nos casos frente e")
        print("verso, 4 folhas soltas no caso 'apenas frente', e grampo no último.")
    else:
        print("Confira os comandos acima e rode de novo com --imprimir.")


if __name__ == "__main__":
    main()
