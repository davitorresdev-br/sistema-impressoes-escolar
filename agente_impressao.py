"""
agente_impressao.py

Este script roda NO COMPUTADOR DO COLÉGIO.
Ele é o único componente do sistema com acesso à impressora física.

O que ele faz, em loop:
  1. Pergunta ao site se existe algum pedido
     "Pendente" — só faz isso dentro do horário permitido (ver
     horario_impressao.py; configurável pelo agente.env).
  2. Para cada pedido encontrado, baixa o PDF, RESERVA o pedido no
     servidor e dispara a impressão usando o automacao_impressora.py.
  3. Avisa o site se deu certo ("Concluído") ou se falhou ("Erro"),
     insistindo até conseguir.

Fora do horário de impressão, ele não imprime nada — mas continua
mandando sinal de vida ao servidor, para a tela dos professores saber que
a impressora está no ar. Os pedidos continuam "Pendente" até o horário
abrir de novo, e são processados na ordem de chegada.

DUAS REGRAS QUE SUSTENTAM A CORRETUDE DAQUI:

  * Confirmar o resultado é OBRIGATÓRIO. Se o papel saiu e a confirmação
    se perde numa falha de rede, o pedido continua 'Pendente' no banco e
    seria IMPRESSO DE NOVO no ciclo seguinte — meia resma jogada fora sem
    deixar rastro óbvio. Por isso atualizar_status() insiste, e o que não
    passa vai para um arquivo de pendências em vez de sumir.

  * A reserva é do SERVIDOR. O agente só imprime o pedido que ele
    conseguiu reservar (o servidor responde 409 se outro agente chegou
    antes). Assim dois agentes rodando por engano não imprimem a mesma
    coisa duas vezes.
"""

import logging
import os
import shutil
import threading
import time as time_module
import uuid
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv

import horario_impressao  # Faixa de horário, compartilhada com o app.py.
from automacao_impressora import disparar_impressao_windows
from opcoes_impressao import ler_int

# Carrega especificamente "agente.env" (não ".env") — assim, se este script
# e o app.py estiverem na mesma pasta durante testes locais, os dois
# arquivos de configuração nunca se confundem.
load_dotenv("agente.env")

# ---------------------------------------------------------------------
# CONFIGURAÇÃO (vem do .env deste mesmo computador — ver agente.env.example)
# ---------------------------------------------------------------------
# Sem CLOUD_URL configurada, o agente fala com o servidor DESTA máquina —
# o arranjo padrão do colégio (app.py e agente no mesmo PC). Defina
# CLOUD_URL no agente.env apenas quando o servidor estiver em outro lugar
# (ex.: hospedado no Discloud).
URL_PADRAO_SERVIDOR = "http://localhost:8080"
CLOUD_URL = (os.environ.get("CLOUD_URL", "").strip() or URL_PADRAO_SERVIDOR).rstrip("/")
AGENTE_API_KEY = os.environ.get("AGENTE_API_KEY", "")
# max(1, ...): intervalo 0 ou negativo virava laço quente (ou explodia no
# time.sleep), martelando o servidor sem parar.
INTERVALO_SEGUNDOS = max(1, ler_int("AGENTE_INTERVALO_SEGUNDOS", 15))
# Fora do horário não há o que fazer a cada 15s: dormir mais evita 3.400
# linhas de log por noite, que soterram justamente o que importa quando
# alguém for diagnosticar algo no console.
INTERVALO_OCIOSO = max(INTERVALO_SEGUNDOS, ler_int("AGENTE_INTERVALO_OCIOSO", 120))

# A faixa de horário vem de horario_impressao.py (configurável pelo
# agente.env). Precisa bater com a do .env do servidor: é o app.py que
# promete ao professor a que horas o pedido vai sair.

PASTA_TEMPORARIA = "temp_impressao"
ARQUIVO_PENDENCIAS = "pendencias_confirmacao.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler("agente.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("agente")

# Uma sessão HTTP só, reaproveitando a conexão TCP. Sem isso era um
# handshake novo por requisição — cerca de 6.000 por dia à toa. De quebra,
# o cabeçalho de autenticação deixa de ser remontado a cada chamada.
sessao_http = requests.Session()
sessao_http.headers.update({"Authorization": f"Bearer {AGENTE_API_KEY}"})


def dentro_do_horario_de_impressao():
    return horario_impressao.dentro_do_horario()


def buscar_pendentes():
    resposta = sessao_http.get(f"{CLOUD_URL}/api/agente/pendentes", timeout=10)
    resposta.raise_for_status()
    return resposta.json().get("pedidos", [])


def baixar_arquivo(pedido_id):
    resposta = sessao_http.get(f"{CLOUD_URL}/api/agente/arquivo/{pedido_id}", timeout=30)
    resposta.raise_for_status()
    return resposta.content


def mandar_sinal_de_vida():
    """Diz ao servidor que o agente está no ar.

    Falha de rede aqui é irrelevante (o próximo sinal tenta de novo), mas
    401/500 vão para o log: chave errada deixaria a tela dos professores
    dizendo "impressora fora do ar" para sempre, sem nenhuma pista."""
    try:
        r = sessao_http.post(f"{CLOUD_URL}/api/agente/heartbeat", timeout=10)
        if r.status_code >= 400:
            log.warning("Sinal de vida recusado pelo servidor (HTTP %s) — confira a "
                        "AGENTE_API_KEY dos dois lados.", r.status_code)
    except requests.RequestException:
        pass


def _bater_coracao_em_segundo_plano():
    """Mantém o sinal de vida durante uma impressão LONGA.

    O laço principal fica preso em subprocess.run até o SumatraPDF
    terminar (até 300s). Sem esta thread, uma apostila grande fazia o
    servidor achar que o agente morreu e a tela anunciar "a impressora
    está fora do ar" justamente enquanto ela imprimia — status mentiroso
    no pior momento possível."""
    while True:
        time_module.sleep(30)
        mandar_sinal_de_vida()


def atualizar_status(pedido_id, novo_status, detalhe=None, reserva=None, tentativas=6):
    """Confirma o resultado no servidor. Devolve True se o servidor aceitou.

    CONFIRMAR É OBRIGATÓRIO: sem confirmação, o pedido continua 'Pendente'
    e é IMPRESSO DE NOVO no ciclo seguinte. Antes, um piscar de rede aqui
    significava 30 cópias saindo duas vezes — o professor recebendo
    material duplicado sem entender por quê, e sem rastro óbvio (parecia
    "erro da impressora"). Por isso insistimos, com espera crescente.

    409 é resposta legítima, não falha: significa que o pedido já não está
    mais disponível (outro agente reservou, ou ele saiu da fila).

    'reserva' é o identificador desta tentativa de impressão. Ele torna a
    reserva idempotente: se a resposta se perder, a retentativa reapresenta
    o mesmo valor e o servidor responde "é sua" em vez de 409 — sem isso, o
    agente desistia de um pedido que ELE MESMO já tinha reservado, e o
    pedido ficava preso sem nada ser impresso.

    Esgotadas as tentativas, o resultado vai para um arquivo de pendências.
    É a diferença entre "perdemos a confirmação e sabemos disso" e
    "reimprimimos às cegas amanhã".
    """
    corpo = {"status": novo_status}
    if detalhe:
        corpo["detalhe"] = detalhe
    if reserva:
        corpo["reserva"] = reserva

    for tentativa in range(tentativas):
        try:
            r = sessao_http.post(
                f"{CLOUD_URL}/api/agente/status/{pedido_id}",
                json=corpo, timeout=10,
            )
            if r.status_code == 409:
                log.warning("Pedido #%s não está mais disponível (409) — pulando.", pedido_id)
                return False
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            espera = min(2 ** tentativa, 30)
            log.warning("Falha ao confirmar '%s' do pedido #%s (%s); nova tentativa em %ss.",
                        novo_status, pedido_id, e, espera)
            time_module.sleep(espera)

    with open(ARQUIVO_PENDENCIAS, "a", encoding="utf-8") as f:
        f.write(f"{horario_impressao.agora().isoformat()}\t{pedido_id}\t{novo_status}\t{detalhe or ''}\n")
    log.error("Não foi possível confirmar '%s' do pedido #%s. Registrado em %s — "
              "confira com o T.I. antes de reimprimir.", novo_status, pedido_id, ARQUIVO_PENDENCIAS)
    return False


def limpar_pasta_temporaria():
    """Apaga PDFs que sobraram de uma execução interrompida.

    O arquivo é removido no `finally` de cada pedido, mas se o processo
    morrer entre gravar e imprimir (queda de energia, Ctrl+C) o PDF fica
    para trás — e são provas, que não devem ficar acumulando em disco."""
    if not os.path.isdir(PASTA_TEMPORARIA):
        return
    try:
        shutil.rmtree(PASTA_TEMPORARIA)
        log.info("Pasta temporária limpa (sobras de execução anterior).")
    except OSError as e:
        log.warning("Não foi possível limpar %s: %s", PASTA_TEMPORARIA, e)


def processar_pedido(pedido):
    pedido_id = pedido["id"]
    # Um identificador por tentativa de impressão. É o que permite ao
    # servidor reconhecer "esta reserva é sua" quando uma resposta se
    # perde, em vez de responder 409 e travar o pedido.
    reserva = uuid.uuid4().hex
    log.info("Processando pedido #%s — %s (%s)",
             pedido_id, pedido["professor_nome"], pedido["materia"])

    # O download vem ANTES de reservar: o status só deve mudar quando
    # houver o que imprimir, senão o professor vê o pedido "saindo" e
    # caindo em "Erro" sem nada ter sido enviado.
    try:
        conteudo_pdf = baixar_arquivo(pedido_id)
    except Exception as e:
        log.error("Erro ao baixar o arquivo do pedido #%s: %s", pedido_id, e)
        atualizar_status(pedido_id, "Erro",
                         "Não foi possível baixar o arquivo do servidor.")
        return

    # RESERVA NO SERVIDOR. Se não conseguirmos reservar (409), outro agente
    # já pegou este pedido — ou ele saiu da fila. Abortar aqui, ANTES de
    # imprimir, é o que impede a impressão em duplicado.
    if not atualizar_status(pedido_id, "Imprimindo", reserva=reserva):
        log.warning("Pedido #%s não reservado — não vou imprimir.", pedido_id)
        return

    os.makedirs(PASTA_TEMPORARIA, exist_ok=True)
    caminho_temporario = os.path.join(PASTA_TEMPORARIA, f"{pedido_id}.pdf")
    with open(caminho_temporario, "wb") as arquivo:
        arquivo.write(conteudo_pdf)

    try:
        sucesso, motivo = disparar_impressao_windows(
            pedido["professor_nome"],
            pedido["materia"],
            pedido["turma"],
            caminho_temporario,
            pedido["copias"],
            pedido["cor"],
            pedido["frente_verso"],
            pedido["acabamento"],
        )
    finally:
        if os.path.exists(caminho_temporario):
            os.remove(caminho_temporario)

    if sucesso:
        # "Concluído" é o valor histórico do banco (relatórios, cota e purga
        # dependem dele), mas o que foi comprovado é a entrega à impressora
        # sem travar na fila. O front-end exibe "Enviado à impressora".
        log.info("Pedido #%s entregue à impressora.", pedido_id)
        atualizar_status(pedido_id, "Concluído", reserva=reserva)
    else:
        log.error("Pedido #%s falhou ao imprimir: %s", pedido_id, motivo)
        atualizar_status(pedido_id, "Erro", motivo, reserva=reserva)


def loop_principal():
    log.info("Agente iniciado. Consultando %s a cada %ss.", CLOUD_URL, INTERVALO_SEGUNDOS)
    if CLOUD_URL == URL_PADRAO_SERVIDOR:
        log.info("(servidor local padrão — defina CLOUD_URL no agente.env para apontar para outro)")
    horario_impressao.avisar_se_desenvolvimento("agente_impressao.py")
    log.info("Horário de impressão: %s.", horario_impressao.descricao())
    limpar_pasta_temporaria()
    # Sinal de vida também DURANTE a impressão (o laço abaixo fica preso no
    # SumatraPDF por até 300s) — senão a tela anuncia "impressora fora do
    # ar" justamente quando ela está imprimindo.
    threading.Thread(target=_bater_coracao_em_segundo_plano, daemon=True).start()

    avisou_fora_do_horario = False

    while True:
        dormir = INTERVALO_SEGUNDOS
        try:
            mandar_sinal_de_vida()
            if dentro_do_horario_de_impressao():
                avisou_fora_do_horario = False
                for pedido in buscar_pendentes():
                    # A janela é conferida A CADA PEDIDO, não uma vez por
                    # ciclo: com 40 pendentes às 17:58, o laço antigo
                    # imprimia todos os 40 depois das 18:00.
                    if not dentro_do_horario_de_impressao():
                        log.info("Horário encerrado — o restante da fila fica para amanhã.")
                        break
                    processar_pedido(pedido)
            else:
                # Uma linha por transição, não uma a cada 15 segundos.
                if not avisou_fora_do_horario:
                    log.info("Fora do horário de impressão (%s) — aguardando.",
                             horario_impressao.descricao())
                    avisou_fora_do_horario = True
                dormir = max(INTERVALO_SEGUNDOS, INTERVALO_OCIOSO)
        except Exception as e:
            log.exception("Erro no ciclo (tentando de novo no próximo intervalo): %s", e)

        time_module.sleep(dormir)


if __name__ == "__main__":
    # CLOUD_URL deixou de ser obrigatória: sem ela, vale o servidor local
    # (URL_PADRAO_SERVIDOR). A chave do agente continua exigida — sem ela
    # nenhuma rota /api/agente/* responde nada de útil.
    if not AGENTE_API_KEY:
        raise SystemExit("Defina AGENTE_API_KEY no agente.env deste computador "
                         "(veja agente.env.example).")
    loop_principal()
