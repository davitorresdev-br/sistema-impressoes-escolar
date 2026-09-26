"""
automacao_impressora.py

Traduz as opções de um pedido em um comando do SumatraPDF e o dispara.

Cor e frente e verso viajam no comando (-print-settings), porque `dmColor` e
`dmDuplex` são campos padrão do DEVMODE do Windows. O GRAMPO não tem campo
padrão: vive na área privada do driver da Konica, que nenhuma ferramenta
genérica escreve. Por isso o grampo é escolhido por FILA, e só por isso são
duas filas em vez de uma.

    Pedido            ->  Fila                    -print-settings
    PB, frente        ->  TI C364 (Normal)        monochrome,simplex
    Color, verso      ->  TI C364 (Normal)        color,duplexlong
    PB, verso, grampo ->  TI C364 (Grampo)        monochrome,duplexlong

As opções vão explícitas em todo trabalho, inclusive quando coincidem com o
padrão do driver. É isso que impede uma fila configurada para 2 faces de
devolver frente e verso a quem pediu só frente.
"""

import os
import subprocess
import time

try:
    import winreg
except ImportError:  # não-Windows: só o agente (que roda no Windows) usa isto
    winreg = None

# O SumatraPDF.exe fica ao lado deste arquivo. Usar o caminho absoluto evita
# depender de qual pasta o agente foi iniciado.
PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
SUMATRAPDF = os.environ.get("SUMATRAPDF_EXE") or os.path.join(PASTA_PROJETO, "SumatraPDF.exe")

# Duas filas, porque só o grampo precisa de fila própria. Os nomes precisam
# ser EXATAMENTE os do Windows (Get-Printer): em impressora compartilhada
# isso inclui o caminho do servidor.
FILAS = {
    False: ("IMPRESSORA_FILA_NORMAL", r"\\SERVIDOR\Impressora (Normal)"),
    True: ("IMPRESSORA_FILA_GRAMPO", r"\\SERVIDOR\Impressora (Grampo)"),
}

# Teto para o SumatraPDF entregar o trabalho ao spooler. Não é o tempo de
# impressão física — o comando volta assim que o job entra na fila. Existe
# para o agente não ficar preso para sempre se algo travar.
TIMEOUT_SEGUNDOS = int(os.environ.get("IMPRESSORA_TIMEOUT_SEGUNDOS", "300"))

CHAVE_FILAS = r"Software\Microsoft\Windows NT\CurrentVersion\Devices"

# Estados do Windows em que mandar o trabalho é jogá-lo num buraco: ele fica
# parado na fila e o professor recebe "Concluído" sem papel nenhum sair.
# Tudo que não estiver aqui é tratado como imprimível — inclusive os estados
# benignos e frequentes (PowerSave, WarmingUp, Busy, TonerLow, Processing).
BLOQUEIA_IMPRESSAO = {
    "Offline",
    "Error",
    "PaperJam",
    "PaperOut",
    "NoToner",
    "DoorOpen",
    "UserInterventionRequired",
    "OutOfMemory",
    "OutputBinFull",
    "NotAvailable",
    "ServerUnknown",
    "PendingDeletion",
    # Fila pausada: o trabalho não se perde, sai quando alguém retomar. Mas
    # até lá o professor estaria olhando "Concluído" sem papel na bandeja.
    "Paused",
}

# Estados de um TRABALHO (não da fila) que significam que ele não vai sair.
# O JobStatus do Windows é combinável ("Printing, Retained"), por isso a
# comparação é por substring e não por igualdade.
TRABALHO_TRAVADO = (
    "error",
    "offline",
    "paperout",
    "blocked",
    "userintervention",
    "deleted",
    "paused",
)

# Quantos segundos observar a fila do servidor depois de entregar o trabalho.
# 0 desliga a verificação. O custo real costuma ser bem menor: assim que a
# fila esvazia, paramos de olhar.
VIGIA_SEGUNDOS = int(os.environ.get("IMPRESSORA_VIGIA_SEGUNDOS", "10"))


def filas_instaladas():
    """
    Nomes das filas como o Windows enxerga, lidos do registro do usuário atual.

    Serve para dar um erro claro ("fila não existe") em vez de o SumatraPDF
    falhar em silêncio — com -silent ele não reclama de impressora inválida.
    Ler do registro do HKEY_CURRENT_USER é de propósito: é lá que ficam as
    conexões de impressora do usuário, e o agente só enxerga as filas da
    conta com que ele foi iniciado.
    """
    if winreg is None:
        return []

    nomes = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_FILAS) as chave:
            indice = 0
            while True:
                try:
                    nome, _valor, _tipo = winreg.EnumValue(chave, indice)
                except OSError:
                    break
                nomes.append(nome)
                indice += 1
    except OSError:
        pass
    return nomes


def estado_da_impressora(nome_fila):
    """
    Consulta o estado da fila antes de enviar. Devolve (estado, detalhe).

    `estado` é "ok", "problema" ou "desconhecido". Só "problema" impede o
    envio — qualquer falha da própria consulta devolve "desconhecido" e o
    trabalho segue. O diagnóstico não pode ser mais frágil que a impressão
    que ele protege.

    Para fila compartilhada (\\\\servidor\\fila) perguntamos ao servidor de
    impressão, não à conexão local: é lá que o estado real vive.
    """
    servidor, fila = _partes_unc(nome_fila)
    alvo = f"-ComputerName '{servidor}' " if servidor else ""
    consulta = f"(Get-Printer {alvo}-Name '{fila}' -ErrorAction Stop).PrinterStatus"

    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", consulta],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return "desconhecido", f"consulta falhou ({e.__class__.__name__})"

    estado = r.stdout.strip()
    if r.returncode != 0 or not estado:
        return "desconhecido", (r.stderr.strip().splitlines() or ["sem resposta"])[0]

    # Lista de BLOQUEIO, não de permissão. O Windows tem dezenas de estados,
    # e a maioria é operação normal: PowerSave, WarmingUp, Busy, TonerLow,
    # Processing, IOActive... Uma lista de permitidos recusaria trabalho com
    # a impressora só dormindo, que é o estado dela na maior parte do dia.
    if estado in BLOQUEIA_IMPRESSAO:
        return "problema", estado
    return "ok", estado


def _partes_unc(nome_fila):
    """('servidor', 'fila') para nome UNC; (None, nome) para fila local."""
    if nome_fila.startswith("\\\\"):
        partes = nome_fila.lstrip("\\").split("\\", 1)
        if len(partes) == 2:
            return partes[0], partes[1]
    return None, nome_fila


def trabalhos_na_fila(nome_fila):
    """
    Trabalhos que a fila do SERVIDOR está mostrando agora.

    Devolve lista de (id, estado) ou None se a consulta não puder ser feita —
    None e lista vazia são coisas diferentes: "não sei" não é "está limpo".
    """
    servidor, fila = _partes_unc(nome_fila)
    alvo = f"-ComputerName '{servidor}' " if servidor else ""
    consulta = (
        f"$j = Get-PrintJob {alvo}-PrinterName '{fila}' -ErrorAction Stop; "
        f"foreach ($x in $j) {{ \"$($x.Id)`t$($x.JobStatus)\" }}"
    )

    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", consulta],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if r.returncode != 0:
        return None

    trabalhos = []
    for linha in r.stdout.splitlines():
        if "\t" in linha:
            ident, _, estado = linha.partition("\t")
            trabalhos.append((ident.strip(), estado.strip()))
    return trabalhos


def acompanhar_fila(nome_fila, ids_antes, segundos=None):
    """
    Observa a fila depois do envio. Devolve (ok, detalhe).

    Só devolve `False` quando o spooler diz EXPLICITAMENTE que um trabalho
    travou. Trabalho ainda imprimindo, fila que não esvaziou dentro da
    janela, ou consulta que falhou não viram erro: uma apostila de 30
    cópias legitimamente demora, e marcar isso como falha seria pior que a
    imprecisão que estamos tentando corrigir.

    Não tentamos identificar exatamente o nosso trabalho. Se a fila tem um
    trabalho travado, o nosso não sai de qualquer forma — a fila é serial.
    """
    segundos = VIGIA_SEGUNDOS if segundos is None else segundos
    if segundos <= 0:
        return True, "vigia desligada"

    limite = time.monotonic() + segundos
    consultou = False

    while time.monotonic() < limite:
        trabalhos = trabalhos_na_fila(nome_fila)
        if trabalhos is None:
            return True, "não deu para consultar a fila do servidor"
        consultou = True

        for ident, estado in trabalhos:
            comparavel = estado.lower().replace(" ", "").replace(",", "")
            for ruim in TRABALHO_TRAVADO:
                if ruim in comparavel:
                    novo = "" if ident in ids_antes else " (recém-enviado)"
                    return False, f"trabalho #{ident}{novo} travado em '{estado}'"

        if not trabalhos:
            return True, "fila esvaziou"

        time.sleep(1)

    return True, "ainda em andamento na fila" if consultou else "sem leitura"


def interpretar_opcoes(cor, acabamento, frente_verso):
    """
    Normaliza as três opções do pedido para booleanos.

    A comparação é tolerante: o front-end manda códigos ("Colorida",
    "Grampeada", "FrenteVerso"), mas estes campos já chegaram a ser
    preenchidos com rótulos por extenso ("Colorido", "Grampeado",
    "Frente e Verso"). Prefixo/substring aceita as duas formas.
    """
    colorida = str(cor).strip().lower().startswith("color")
    grampeada = "grampe" in str(acabamento).strip().lower()
    duplex = "verso" in str(frente_verso).strip().lower()
    return colorida, grampeada, duplex


def mapear_fila_impressora(cor, acabamento, frente_verso=""):
    """
    A fila depende SÓ do grampo — cor e frente e verso vão no comando.

    `cor` e `frente_verso` continuam na assinatura porque quem chama passa as
    três opções juntas, e para não quebrar quem já usava esta função.
    """
    _colorida, grampeada, _duplex = interpretar_opcoes(cor, acabamento, frente_verso)
    variavel, padrao = FILAS[grampeada]
    return os.environ.get(variavel, padrao).strip()


def montar_print_settings(colorida, duplex, copias):
    """
    Monta o -print-settings do SumatraPDF (lista separada por vírgula).

    Sempre explícito nas duas dimensões: mandar "simplex" quando o pedido é
    só frente é o que impede a fila de grampo (hoje em TwoSidedLongEdge) de
    devolver frente e verso para quem não pediu.

    Só entram tokens que a versão 3.6.1 do SumatraPDF conhece de fato — a
    documentação online descreve uma versão mais nova e lista opções que
    este binário não tem (`collate`, `ignore-pdf-print-settings`). Token
    desconhecido é ignorado em silêncio, o que daria papel errado sem
    nenhuma mensagem de erro.

    Sem `collate`, a intercalação segue o padrão do driver da Konica (que
    vem ligado). Se algum dia sair 30 páginas 1, depois 30 páginas 2, é aí
    que se olha.
    """
    partes = []

    if copias > 1:
        partes.append(f"{copias}x")

    partes.append("color" if colorida else "monochrome")
    partes.append("duplexlong" if duplex else "simplex")

    return ",".join(partes)


def disparar_impressao_windows(professor_nome, materia, turma, caminho_pdf, copias, cor, frente_verso, acabamento):
    colorida, grampeada, duplex = interpretar_opcoes(cor, acabamento, frente_verso)
    nome_impressora = mapear_fila_impressora(cor, acabamento, frente_verso)

    try:
        copias_int = max(1, int(str(copias).strip()))
    except (TypeError, ValueError):
        copias_int = 1

    print_settings = montar_print_settings(colorida, duplex, copias_int)

    comando = [
        SUMATRAPDF,
        "-print-to", nome_impressora,
        "-print-settings", print_settings,
        # -silent: nenhuma janela de erro. Sem isso, qualquer problema abre um
        # diálogo no PC da impressora e o agente fica preso até alguém clicar.
        "-silent",
        # -exit-when-done: garante que o processo termine e o subprocess volte.
        "-exit-when-done",
        caminho_pdf,
    ]

    print(f"💻 [Pedido] {professor_nome} — {materia} ({turma})")
    print(f"💻 [Opções] {copias_int}x | cor={cor} | página={frente_verso} | acabamento={acabamento}")

    # O SumatraPDF com -silent não reclama de impressora inexistente nem de
    # arquivo ausente: ele simplesmente não imprime e sai com 0. Conferimos
    # antes para o pedido virar "Erro" com motivo, em vez de "Concluído"
    # sem papel nenhum saindo.
    if not os.path.exists(caminho_pdf):
        print(f"❌ [Erro] arquivo PDF não encontrado: {caminho_pdf}")
        return False

    instaladas = filas_instaladas()
    if instaladas and nome_impressora.casefold() not in {f.casefold() for f in instaladas}:
        print(f"❌ [Erro] a fila '{nome_impressora}' não existe no Windows para o usuário do agente.")
        print(f"   Filas visíveis: {', '.join(instaladas)}")
        return False

    estado, detalhe = estado_da_impressora(nome_impressora)
    if estado == "problema":
        print(f"❌ [Erro] a impressora está em '{detalhe}' — trabalho não enviado.")
        print("   O pedido volta como Erro em vez de sumir numa fila parada.")
        return False
    if estado == "desconhecido":
        print(f"⚠️ [Aviso] não deu para conferir o estado da impressora ({detalhe}). Enviando assim mesmo.")

    # Quem já estava na fila antes de nós. Serve só para o log distinguir
    # "o trabalho recém-enviado travou" de "a fila já estava travada".
    antes = trabalhos_na_fila(nome_impressora) or []
    ids_antes = {ident for ident, _estado in antes}

    # Depois das guardas, para o log não anunciar um comando que pode não
    # chegar a rodar.
    print(f"💻 [Terminal Windows] Executando: {subprocess.list2cmdline(comando)}")

    try:
        subprocess.run(comando, check=True, timeout=TIMEOUT_SEGUNDOS)

        # O SumatraPDF volta assim que entrega ao spooler — daí em diante,
        # quem sabe algo é a fila do servidor. Olhamos por alguns segundos
        # para pegar trabalho que empaca (papel, atolamento, fila parada).
        entregue, nota = acompanhar_fila(nome_impressora, ids_antes)
        if not entregue:
            print(f"❌ [Erro] {nota} — o papel não vai sair.")
            return False

        print(f"🖨️ [Enviado] Fila '{nome_impressora}' ({print_settings}) — {nota}")
        return True
    except FileNotFoundError:
        print(f"❌ [Erro] SumatraPDF.exe não encontrado em {SUMATRAPDF}")
        return False
    except subprocess.TimeoutExpired:
        print(f"❌ [Erro] SumatraPDF não respondeu em {TIMEOUT_SEGUNDOS}s — trabalho abortado.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ [Erro] SumatraPDF falhou com código {e.returncode}.")
        return False
