"""
horario_impressao.py

Uma definição só de "está no horário de imprimir", usada pelo servidor
(app.py) e pelo agente (agente_impressao.py). Nenhum dos dois deve ter a
sua própria cópia da faixa, nem o texto do horário escrito à mão: basta um
ficar para trás para o sistema prometer uma coisa e fazer outra.

Configuração — os mesmos nomes no `.env` do servidor e no `agente.env`:

    HORARIO_INICIO_IMPRESSAO=08:00
    HORARIO_FIM_IMPRESSAO=18:00
    HORARIO_SO_DIAS_UTEIS=false

Os dois processos rodam em máquinas diferentes, cada um com o seu arquivo.
Se os valores divergirem, o professor recebe uma promessa que o agente não
cumpre — mantenha iguais.

O fuso é fixo em America/Sao_Paulo de propósito: não é um botão que alguém
precise girar, e deixá-lo configurável só criaria mais uma forma de os dois
lados discordarem.
"""

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")

INICIO_PADRAO = time(8, 0)
FIM_PADRAO = time(18, 0)


def _ler_hora(variavel, padrao):
    """
    Lê "HH:MM" do ambiente. Valor inválido cai no padrão, com aviso.

    A leitura é feita na hora do uso, não na importação: o
    agente_impressao.py importa este módulo ANTES de chamar
    load_dotenv("agente.env"), e ler cedo demais ignoraria o arquivo
    inteiro em silêncio.

    Diante de lixo na configuração, avisa e segue com o padrão em vez de
    derrubar o processo — agente parado não imprime nada, e o erro pode
    aparecer justo no meio do expediente.
    """
    bruto = os.environ.get(variavel, "").strip()
    if not bruto:
        return padrao

    try:
        horas, minutos = bruto.split(":")
        return time(int(horas), int(minutos))
    except (ValueError, TypeError):
        print(f"⚠️ [Horário] {variavel}={bruto!r} não é HH:MM — usando {padrao.strftime('%H:%M')}.")
        return padrao


def janela():
    """(início, fim) do horário de impressão."""
    return (
        _ler_hora("HORARIO_INICIO_IMPRESSAO", INICIO_PADRAO),
        _ler_hora("HORARIO_FIM_IMPRESSAO", FIM_PADRAO),
    )


def so_dias_uteis():
    return os.environ.get("HORARIO_SO_DIAS_UTEIS", "").strip().lower() in ("1", "true", "sim")


def modo_desenvolvimento():
    """
    MODO_DESENVOLVIMENTO=true ignora a faixa de horário.

    Existe para testar fora do expediente sem precisar editar a faixa nos
    dois `.env` e lembrar de desfazer os dois depois.

    Só afeta o horário. Não é um "modo de teste" que desliga verificações
    ou desvia a impressão: ligado, o agente imprime de verdade, na Konica
    de verdade.
    """
    return os.environ.get("MODO_DESENVOLVIMENTO", "").strip().lower() in ("1", "true", "sim")


def avisar_se_desenvolvimento(processo):
    """Grita no console quando o modo está ligado.

    Ligado sem querer em produção, o sistema imprime de madrugada e ninguém
    percebe — o único sintoma seria papel saindo fora de hora. Por isso o
    aviso é feio de propósito, e sai na inicialização dos dois processos.
    """
    if modo_desenvolvimento():
        print("=" * 66)
        print(f"  ATENÇÃO: MODO_DESENVOLVIMENTO ligado em {processo}.")
        print("  A faixa de horário está sendo IGNORADA — imprime a qualquer hora.")
        print("  Remova MODO_DESENVOLVIMENTO do .env antes de usar em produção.")
        print("=" * 66)


def agora():
    return datetime.now(FUSO_HORARIO)


def dentro_do_horario(momento=None):
    if modo_desenvolvimento():
        return True

    momento = momento or agora()
    inicio, fim = janela()

    if so_dias_uteis() and momento.weekday() >= 5:  # 5 = sábado, 6 = domingo
        return False

    hora = momento.time()
    if inicio <= fim:
        return inicio <= hora <= fim

    # Janela que atravessa a meia-noite (ex.: 22:00–06:00). Improvável numa
    # escola, mas sem este caso a configuração viraria "nunca imprime", que
    # é bem difícil de diagnosticar olhando só o console.
    return hora >= inicio or hora <= fim


def descricao():
    """"08:00–18:00", para as mensagens — sempre coerente com a configuração."""
    if modo_desenvolvimento():
        return "sem limite de horário (modo de desenvolvimento)"
    inicio, fim = janela()
    texto = f"{inicio.strftime('%H:%M')}–{fim.strftime('%H:%M')}"
    return f"{texto}, em dias úteis" if so_dias_uteis() else texto


def hora_de_abertura():
    """Só o início, para o texto "será impresso a partir das …"."""
    return janela()[0].strftime("%H:%M")
