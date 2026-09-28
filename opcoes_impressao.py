"""
opcoes_impressao.py

Regras de opções de impressão que o SERVIDOR e o AGENTE precisam entender
do mesmo jeito, e a leitura de configuração numérica do ambiente.

Existe pelo mesmo motivo do horario_impressao.py: quando a mesma regra é
escrita duas vezes (uma no app.py, outra no automacao_impressora.py), basta
uma delas ficar para trás para o sistema prometer uma coisa e fazer outra.
O servidor precisa saber o que é "frente e verso" para contar folhas de
papel; o agente precisa saber a mesma coisa para montar o comando da
impressora. A definição mora aqui, e os dois importam.

Este módulo é de propósito sem dependências: nada de Windows, registro,
banco ou Flask. Assim tanto o servidor (Linux/Discloud) quanto o agente
(Windows do colégio) podem importá-lo sem arrastar nada consigo.
"""

import math
import os


def ler_int(variavel, padrao):
    """Lê um inteiro do ambiente. Valor inválido AVISA e cai no padrão, em
    vez de derrubar o processo.

    Mesmo raciocínio do _ler_hora em horario_impressao.py: um
    `AGENTE_INTERVALO_SEGUNDOS=15s` (com "s") não pode matar o agente na
    inicialização — agente parado não imprime nada, e o erro apareceria
    justo no meio do expediente, sem ninguém olhando o console.
    """
    bruto = os.environ.get(variavel, "").strip()
    if not bruto:
        return padrao
    try:
        return int(bruto)
    except (TypeError, ValueError):
        print(f"⚠️ [Config] {variavel}={bruto!r} não é um número inteiro — usando {padrao}.")
        return padrao


def interpretar_opcoes(cor, acabamento, frente_verso):
    """Normaliza as três opções do pedido para booleanos.

    A comparação é tolerante: o front-end manda códigos ("Colorida",
    "Grampeada", "FrenteVerso"), mas estes campos já chegaram a ser
    preenchidos com rótulos por extenso ("Colorido", "Grampeado",
    "Frente e Verso"). Prefixo/substring aceita as duas formas — e os dois
    formatos existem no banco de produção, então a tolerância não é
    hipotética.
    """
    colorida = str(cor).strip().lower().startswith("color")
    grampeada = "grampe" in str(acabamento).strip().lower()
    duplex = "verso" in str(frente_verso).strip().lower()
    return colorida, grampeada, duplex


def folhas_do_pedido(paginas, copias, frente_verso, paginas_por_folha=1):
    """FOLHAS DE PAPEL do pedido — a unidade da bandeja, do armário e da
    compra de resma. Não confundir com "impressões" (páginas × cópias), que
    é a unidade do toner e do contador da Konica.

    O arredondamento é POR DOCUMENTO, e é por isso que folhas não pode ser
    derivada de um total agregado: 7 páginas em frente e verso ocupam 4
    folhas (a última sai com o verso em branco), não 3,5. Dividir a soma de
    um relatório por 2 erra em todo pedido de página ímpar.

    `paginas_por_folha` fica parametrizável para o dia em que entrar o "2
    páginas por folha" do driver (2up): aí o divisor vira 4 em duplex, sem
    ninguém precisar caçar um número mágico em três arquivos.

    Página sem contagem (PDF que o pypdf não leu) entra como 0 — quem
    valida teto de folhas deve tratar "não sei quantas páginas" antes de
    chegar aqui, não deixar passar como zero.
    """
    try:
        paginas = max(0, int(paginas or 0))
        copias = max(1, int(copias or 1))
    except (TypeError, ValueError):
        return 0

    _cor, _grampo, duplex = interpretar_opcoes("", "", frente_verso)
    por_folha = max(1, int(paginas_por_folha or 1)) * (2 if duplex else 1)
    return math.ceil(paginas / por_folha) * copias
