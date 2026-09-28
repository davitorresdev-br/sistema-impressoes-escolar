import os
import csv
import hashlib
import hmac
import io
import logging
import re
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import banco_dados as db  # Toda a lógica de usuários, senhas e privilégios
                           # de Admin vive em banco_dados/ — não aqui.
import horario_impressao  # Faixa de horário, compartilhada com o agente.
from horario_impressao import FUSO_HORARIO
# Regras de opções de impressão compartilhadas com o agente (o servidor
# precisa saber o que é "frente e verso" para contar folhas de papel).
from opcoes_impressao import folhas_do_pedido, interpretar_opcoes, ler_int

# Carrega o arquivo .env (se existir) para dentro de os.environ, ANTES de
# qualquer os.environ.get() abaixo. Sem essa linha, o .env não tem efeito
# nenhum — ele é só um arquivo de texto até alguém ler ele.
load_dotenv()

# LOG EM ARQUIVO, com data e hora. Quando uma professora diz "mandei
# imprimir ontem de manhã e não saiu", tem que existir onde olhar — o
# console já rolou, e print() sem carimbo de tempo não ajuda ninguém.
# Rotativo para não crescer sem limite no servidor da escola.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            os.environ.get("ACALANTO_LOG", "servidor.log"),
            maxBytes=5_000_000, backupCount=5, encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("acalanto")

# O front-end COMPILADO, quando existir, é servido por este mesmo processo.
# Ganho triplo: um processo em vez de dois; bundle minificado (carga muito
# menor na rede do colégio que o servidor de desenvolvimento do Vite); e
# mesma origem, o que dispensa o CORS. Se a pasta dist/ não existir, nada
# muda — o Vite continua servindo o front na 5173 como antes.
_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Front-end", "dist")
_TEM_DIST = os.path.isfile(os.path.join(_DIST, "index.html"))

if _TEM_DIST:
    app = Flask(__name__, static_folder=_DIST, static_url_path="")
else:
    app = Flask(__name__)

# ATRÁS DE UM PROXY REVERSO (nginx na VM Linux): sem isto, request.remote_addr
# é sempre 127.0.0.1 — o endereço do próprio nginx. Consequência grave: o
# limite de tentativas de login passa a contar TODO MUNDO junto, e cinco
# senhas erradas de uma pessoa trancariam o login do colégio inteiro.
# ProxyFix lê o X-Forwarded-For que o nginx envia e devolve o IP real.
#
# Fica atrás de uma chave porque confiar nesse cabeçalho sem proxy na frente
# é o contrário de segurança: qualquer cliente poderia forjar o próprio IP e
# escapar do limite. Ligue APENAS quando houver mesmo um proxy.
if os.environ.get("ACALANTO_ATRAS_DE_PROXY", "false").strip().lower() == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


@app.route('/')
def raiz():
    """A tela do sistema (quando há build) ou uma resposta honesta de que
    só a API está de pé."""
    if _TEM_DIST:
        return app.send_static_file('index.html')
    return jsonify({
        "servico": "Sistema de Impressão — API",
        "front": "não compilado (rode 'npm run build' em Front-end/ para servir a tela por aqui)",
    })

# Tamanho máximo de qualquer requisição (50 MB). O front-end já recusa
# arquivos maiores, mas o cliente não é confiável: sem este limite no
# servidor, dava para encher o banco com um único upload gigante.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# Origens liberadas no CORS. Por padrão "*" (qualquer uma) para não
# quebrar o acesso pela rede do colégio, mas dá para restringir definindo
# ACALANTO_CORS_ORIGINS no .env (lista separada por vírgula).
_origens_env = os.environ.get("ACALANTO_CORS_ORIGINS", "*").strip()
_origens_cors = "*" if _origens_env == "*" else [o.strip() for o in _origens_env.split(",") if o.strip()]
CORS(app, resources={
    r"/api/*": {
        "origins": _origens_cors,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": "*"
    }
})

# ID do cliente OAuth do Google Workspace. Não é um segredo (é o mesmo
# valor que já fica visível no front-end), mas fica mais fácil de trocar
# sem editar código se algum dia mudar — definido no .env como
# GOOGLE_CLIENT_ID. O valor abaixo é só o padrão, caso o .env não exista.
GOOGLE_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    ""
)

# Chave secreta que só o agente de impressão (rodando no computador do
# colégio) conhece. Protege as rotas /api/agente/* — sem essa chave, elas
# nunca respondem nada de útil, mesmo se alguém descobrir a URL.
AGENTE_API_KEY = os.environ.get("AGENTE_API_KEY", "")

# Chave usada para ASSINAR os tokens de sessão dos usuários (professores e
# TI). Quem faz login recebe um token assinado com ela; as rotas /api/fila
# e /api/enviar confiam apenas no que está dentro desse token, e não mais
# no nome que o navegador manda na URL. Defina ACALANTO_SECRET_KEY no .env;
# o valor abaixo é só um padrão inseguro para desenvolvimento local.
SECRET_KEY = os.environ.get("ACALANTO_SECRET_KEY", "dev-inseguro-troque-no-env")
TOKEN_VALIDADE_SEGUNDOS = 60 * 60 * 12  # Sessão expira em 12 horas.
_serializador_token = URLSafeTimedSerializer(SECRET_KEY, salt="sessao-usuario")

# COTA mensal em FOLHAS DE PAPEL por usuário. 0 = ilimitado (padrão).
# Quando > 0, /api/enviar recusa o pedido que faria o usuário estourar o
# limite no mês.
#
# A unidade é folha (e não "impressões" = páginas × cópias, como era antes)
# porque folha é o que acaba no armário e o que a escola compra — e porque
# duas unidades para a mesma coisa no mesmo sistema garantem erro de
# leitura. Efeito colateral desejado: em folhas, frente e verso consome
# metade da cota, então a métrica passa a induzir o que economiza papel.
# O nome antigo da variável continua aceito para não quebrar .env em uso.
LIMITE_MENSAL_FOLHAS = ler_int(
    "ACALANTO_LIMITE_MENSAL_FOLHAS",
    ler_int("ACALANTO_LIMITE_MENSAL_IMPRESSOES", 0),
)

# TETO DE FOLHAS POR ENVIO. A regra do colégio é 500 folhas por pedido;
# acima disso é tiragem grande, que passa pelo T.I. Sem este teto, um zero
# a mais nas cópias (300 -> 3000) entra na fila sem nenhuma barreira.
MAX_FOLHAS_POR_PEDIDO = ler_int("ACALANTO_MAX_FOLHAS", 500)

# RETENÇÃO: depois de quantos dias o conteúdo de um PDF já impresso é
# descartado (mantendo o registro e o hash para auditoria). 0 = nunca
# descartar (padrão). Roda na inicialização e uma vez por dia (ver
# _rotina_de_manutencao).
RETENCAO_DIAS = ler_int("ACALANTO_RETENCAO_DIAS", 0)

# Depois de quantos minutos em 'Imprimindo' um pedido é considerado preso
# e devolvido à fila (o agente caiu no meio). Cobre com folga o pior caso
# legítimo: o timeout do SumatraPDF é de 300s, mais a vigia da fila.
MINUTOS_PEDIDO_PRESO = ler_int("ACALANTO_MINUTOS_PEDIDO_PRESO", 20)

# Quanto tempo sem sinal do agente já conta como "impressora fora do ar"
# na tela dos professores. O agente manda sinal a cada ciclo (15s), então
# 90s significa três ciclos perdidos — não é um piscar de rede.
SEGUNDOS_AGENTE_OFFLINE = ler_int("ACALANTO_SEGUNDOS_AGENTE_OFFLINE", 90)

# AUTO-CADASTRO: "aberto" (padrão, comportamento atual) deixa qualquer um
# que alcance o servidor criar a própria conta de professor; "fechado" faz
# /api/registrar recusar e as contas passam a nascer só pelo painel do T.I.
# Numa rede em que os alunos têm Wi-Fi, "aberto" é uma porta de entrada
# real — recomendação: fechar e cadastrar pelo painel.
AUTOCADASTRO = os.environ.get("ACALANTO_AUTOCADASTRO", "aberto").strip().lower()

# Senha mínima. 4 caracteres somados a login sem limite de tentativas é
# força bruta em segundos; 8 é o mínimo defensável hoje.
SENHA_MINIMA = ler_int("ACALANTO_SENHA_MINIMA", 8)

# Horário em que a impressora "aceita" trabalhos. Fora dessa faixa, os
# pedidos ficam represados como Pendente normalmente — o agente local que
# decide não imprimir fora do expediente (ver agente_impressao.py).
# A faixa vem de horario_impressao.py, compartilhado com o agente, e é
# configurável pelo .env (HORARIO_INICIO_IMPRESSAO / HORARIO_FIM_IMPRESSAO).

db.init_db()
horario_impressao.avisar_se_desenvolvimento("app.py")


def _manutencao(origem):
    """Devolve à fila os pedidos presos e aplica a política de retenção.

    As duas tarefas rodam na inicialização e uma vez por dia. Antes, a
    retenção só rodava ao subir o servidor: com o servidor meses no ar (o
    desejável), a política simplesmente nunca se aplicava."""
    try:
        presos = db.sinalizar_pedidos_presos(MINUTOS_PEDIDO_PRESO)
        if presos:
            # Sinalizados como Erro, NÃO reenviados: o papel pode ter saído,
            # e reimprimir sozinho desperdiçaria a tiragem inteira.
            log.warning("[%s] %d pedido(s) preso(s) em 'Imprimindo' marcado(s) como Erro "
                        "(estado desconhecido — conferir a bandeja, sem reenvio automático).",
                        origem, presos)
        if RETENCAO_DIAS > 0:
            purgados = db.purgar_pdfs_antigos(RETENCAO_DIAS)
            if purgados:
                log.info("[%s] Conteúdo de %d PDF(s) descartado (> %d dias).",
                         origem, purgados, RETENCAO_DIAS)
    except Exception:
        # Manutenção que falha não pode derrubar o servidor nem a thread.
        log.exception("[%s] falha na rotina de manutenção", origem)


_manutencao("inicialização")


def _rotina_de_manutencao():
    """Roda a manutenção a cada hora, em segundo plano.

    Uma hora (e não um dia) porque o reaper de pedidos presos é o que
    devolve à fila o trabalho de quem desligou o PC da impressora — deixar
    isso para o dia seguinte significaria a professora esperando até amanhã
    por um pedido que ninguém mais ia olhar."""
    while True:
        time.sleep(3600)
        _manutencao("rotina")


threading.Thread(target=_rotina_de_manutencao, daemon=True).start()

# CONTROLE DE TENTATIVAS DE LOGIN, na memória do processo. Guardar em
# memória é suficiente para uma escola (um processo só) e não exige
# dependência nova: reiniciar o servidor zera a contagem, o que é
# aceitável — o objetivo é impedir força bruta, não auditar tentativa.
#
# A contagem é POR IP, não por nome de usuário, por dois motivos que
# aprendemos revisando isto:
#   1. Chave por usuário é memória controlada por quem ataca: cada nome
#      inventado numa requisição criava uma entrada nova no dicionário,
#      sem autenticação nenhuma. Bastava um laço para esgotar a memória.
#   2. Chave por usuário tranca a conta ALHEIA: 5 tentativas erradas de um
#      terceiro deixavam a professora sem entrar na própria conta, o que é
#      negação de serviço em vez de proteção.
# O IP é o que de fato identifica quem está tentando, e o dicionário tem
# teto — cheio, ele descarta as entradas mais antigas em vez de crescer.
_tentativas_login = defaultdict(list)
LOGIN_MAX_TENTATIVAS = ler_int("ACALANTO_LOGIN_MAX_TENTATIVAS", 5)
LOGIN_JANELA_SEGUNDOS = ler_int("ACALANTO_LOGIN_JANELA_SEGUNDOS", 300)
LOGIN_MAX_CHAVES = 5000  # teto do dicionário (uma entrada por IP)


def _chave_tentativas():
    """A origem da requisição. Sempre um valor nosso, nunca texto do
    cliente — assim ninguém escolhe a chave do dicionário."""
    return request.remote_addr or "desconhecido"


def _excedeu_tentativas():
    agora = time.monotonic()
    chave = _chave_tentativas()
    recentes = [t for t in _tentativas_login.get(chave, ()) if agora - t < LOGIN_JANELA_SEGUNDOS]
    if recentes:
        _tentativas_login[chave] = recentes
    else:
        _tentativas_login.pop(chave, None)
    return len(recentes) >= LOGIN_MAX_TENTATIVAS


def _registrar_tentativa():
    # Faxina preguiçosa: só quando o dicionário passa do teto, e sempre
    # jogando fora o que já venceu antes de recorrer ao corte por idade.
    if len(_tentativas_login) > LOGIN_MAX_CHAVES:
        agora = time.monotonic()
        for chave in [k for k, v in _tentativas_login.items()
                      if not v or agora - max(v) >= LOGIN_JANELA_SEGUNDOS]:
            _tentativas_login.pop(chave, None)
        while len(_tentativas_login) > LOGIN_MAX_CHAVES:
            _tentativas_login.pop(min(_tentativas_login, key=lambda k: max(_tentativas_login[k])), None)
    _tentativas_login[_chave_tentativas()].append(time.monotonic())


def _limpar_tentativas():
    """Login certo limpa o contador — senão quem erra 4 vezes e acerta na
    quinta ficaria a um erro do bloqueio pelo resto da janela."""
    _tentativas_login.pop(_chave_tentativas(), None)


def dentro_do_horario_de_impressao():
    return horario_impressao.dentro_do_horario()


def mensagem_para_envio():
    if dentro_do_horario_de_impressao():
        return "Pedido enviado para a fila de impressão com sucesso!"
    # O horário sai da configuração, nunca escrito à mão aqui: o texto tem
    # que acompanhar a faixa que o agente realmente cumpre.
    return (
        f"Pedido recebido! Fora do horário de impressão ({horario_impressao.descricao()}), "
        f"ele vai entrar na fila e será impresso a partir das "
        f"{horario_impressao.hora_de_abertura()}, respeitando a ordem de chegada."
    )


def verificar_chave_agente():
    """Confere se a requisição trouxe a chave secreta correta do agente
    de impressão. Sem AGENTE_API_KEY configurado no .env, nega tudo —
    nunca libera por padrão.

    hmac.compare_digest e não '==': a comparação de string comum sai no
    primeiro byte diferente, e essa diferença de tempo, medida muitas
    vezes, vaza a chave byte a byte. O ataque é difícil pela rede, mas a
    correção custa uma linha."""
    if not AGENTE_API_KEY:
        return False
    # Comparação em BYTES: com str, um cabeçalho não-ASCII faz o
    # compare_digest levantar TypeError, que virava 500 em vez de 401.
    return hmac.compare_digest(
        request.headers.get("Authorization", "").encode("utf-8", "replace"),
        f"Bearer {AGENTE_API_KEY}".encode("utf-8"),
    )


def gerar_token_sessao(usuario):
    """Cria um token assinado com a identidade do usuário. Esse token é a
    única prova de identidade aceita por /api/fila e /api/enviar — o nome,
    o papel e o identificador único (uid) nunca mais vêm 'soltos' na URL.
    O uid (username local ou e-mail Workspace) é o que amarra cada pedido
    a uma conta específica, sem depender do nome (que pode se repetir).

    'segmentos' (lista — a conta pode participar de mais de um) vai junto
    para escopo_de_visao() poder decidir o que uma COORDENACAO enxerga sem
    reconsultar o banco a cada requisição. 'segmento' (único) segue no token
    para os pontos que precisam de UM valor (ex.: pré-preencher formulário).
    Contas Workspace (login Google, hoje sem botão no front) não têm essa
    coluna — .get() devolve None/[] nesse caso, que cai no ramo mais
    restritivo."""
    return _serializador_token.dumps({
        "name": usuario["name"],
        "role": usuario["role"],
        "isSuperAdmin": usuario["isSuperAdmin"],
        "uid": usuario.get("uid", ""),
        "metodo": usuario.get("metodo", ""),
        "segmento": usuario.get("segmento"),
        "segmentos": db.normalizar_segmentos(usuario.get("segmentos") or usuario.get("segmento")),
        # Versão do token: trocar a senha incrementa o número no banco e
        # derruba este token na próxima requisição (ver usuario_autenticado).
        "tv": usuario.get("token_version", 0),
    })


def bloqueado_por_modo_desenvolvimento(usuario):
    """Em MODO_DESENVOLVIMENTO, só o administrador-mestre usa o sistema.

    Testar fora do expediente significa imprimir de verdade em horário
    esquisito. Se um professor entrasse nesse intervalo, os trabalhos dele
    se misturariam aos de teste na mesma Konica, e ele receberia papel que
    não pediu — ou não receberia o que pediu, porque alguém está mexendo na
    fila. Fechar o acesso é o que torna o modo seguro de usar.

    O critério é `super_admin` no banco, não o cargo T.I.: o cargo pode ser
    dado a várias pessoas do Departamento, enquanto o administrador-mestre
    é a conta única de quem está conduzindo o teste.

    Não vale para as rotas do agente — elas usam AGENTE_API_KEY e precisam
    continuar funcionando, senão não há o que testar.
    """
    return horario_impressao.modo_desenvolvimento() and not usuario.get("isSuperAdmin")


def usuario_autenticado():
    """Lê o cabeçalho Authorization: Bearer <token>, valida a assinatura e
    a validade, e devolve os dados do usuário. Retorna None se faltar o
    token, se ele tiver sido adulterado ou se já tiver expirado.

    Em modo de desenvolvimento, também devolve None para quem não é o
    administrador-mestre — inclusive para sessões abertas ANTES de o modo
    ser ligado, que de outra forma continuariam valendo até expirar.

    Também recusa token cuja senha já foi trocada depois da emissão: o
    número 'tv' dentro do token tem que bater com o token_version da conta.
    É isso que torna uma senha comprometida revogável de verdade, em vez de
    "válida até expirar em 12h"."""
    cabecalho = request.headers.get("Authorization", "")
    if not cabecalho.startswith("Bearer "):
        return None
    token = cabecalho[len("Bearer "):].strip()
    try:
        usuario = _serializador_token.loads(token, max_age=TOKEN_VALIDADE_SEGUNDOS)
    except (BadSignature, SignatureExpired):
        return None

    if bloqueado_por_modo_desenvolvimento(usuario):
        return None

    # Só contas locais têm versão de token (as Workspace não moram em
    # usuarios_locais). Token antigo, de antes deste campo existir, não
    # traz 'tv' — nesse caso não derrubamos a sessão à toa: ela expira em
    # 12h de qualquer forma.
    if usuario.get("metodo") == "local" and "tv" in usuario:
        versao_atual = db.obter_token_version(usuario.get("uid", ""))
        if versao_atual is None or versao_atual != usuario.get("tv"):
            return None
    return usuario


def escopo_de_visao(sessao):
    """Resolve, a partir da SESSÃO (que vem do token assinado — nunca de um
    parâmetro que o cliente possa forjar), o que esta pessoa pode enxergar.

    Retorna uma tupla (escopo, segmentos):
      ("TUDO", None)                 -> T.I., Diretoria, COORDENACAO com GERAL
      ("SEGMENTO", ["FUND1", ...])   -> COORDENACAO daqueles segmentos (a
                                        conta pode participar de mais de um;
                                        a lista nunca vem vazia neste caso)
      ("PROPRIO", None)              -> professor comum e caso não reconhecido

    Regra de ouro: o 'else' final é sempre PROPRIO. Papel desconhecido,
    conta apagada ou COORDENACAO sem nenhum segmento válido caem no mais
    restritivo — nunca no mais permissivo. Centralizado aqui porque escopo
    espalhado por rota é como vaza permissão: toda rota que decide "o que
    esta pessoa vê" deve chamar esta função, não reimplementar a regra.

    Tokens antigos (de antes da lista) trazem só 'segmento' — o fallback
    para ele mantém essas sessões funcionando até expirarem (12h).
    """
    role = sessao.get("role")
    if role == db.ROLE_TI or role in db.PAPEIS_DIRETORIA:
        return ("TUDO", None)
    if role == db.ROLE_COORDENACAO:
        segmentos = db.normalizar_segmentos(sessao.get("segmentos") or sessao.get("segmento"))
        if db.SEGMENTO_GERAL in segmentos:
            return ("TUDO", None)
        if segmentos:
            return ("SEGMENTO", segmentos)
    return ("PROPRIO", None)


@app.errorhandler(413)
def arquivo_grande_demais(_erro):
    return jsonify({"erro": "Arquivo excede o limite de 50 MB."}), 413

@app.route('/api/horario', methods=['GET'])
def api_horario():
    """Faixa de horário para o front-end exibir.

    Sem autenticação de propósito: é a mesma informação que já fica visível
    na tela de envio, e o painel lateral precisa dela antes de qualquer
    ação do usuário.
    """
    inicio, fim = horario_impressao.janela()
    # SINAL DE VIDA DO AGENTE. Sai por aqui porque o painel lateral já
    # consulta esta rota — o professor precisa saber que a impressora está
    # fora do ar ANTES de estranhar que o papel não saiu. Sem isso, PC
    # desligado significa pedidos acumulando com todo mundo achando que
    # está tudo bem (o modo de falha mais provável do sistema).
    visto_em, segundos = db.estado_do_agente()
    return jsonify({
        "inicio": inicio.strftime("%H:%M"),
        "fim": fim.strftime("%H:%M"),
        "so_dias_uteis": horario_impressao.so_dias_uteis(),
        "descricao": horario_impressao.descricao(),
        "aberto_agora": horario_impressao.dentro_do_horario(),
        "modo_desenvolvimento": horario_impressao.modo_desenvolvimento(),
        # None = nunca houve sinal (agente ainda não subiu, ou é uma versão
        # anterior ao heartbeat). Nesse caso o front não acusa nada: dizer
        # "fora do ar" sem saber seria alarme falso.
        "agente_online": None if segundos is None else segundos <= SEGUNDOS_AGENTE_OFFLINE,
        "agente_visto_em": visto_em,
        "agente_segundos": segundos,
    })


# -------------------------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO
# -------------------------------------------------------------------------

@app.route('/api/login', methods=['POST'])
def login_credenciais():
    try:
        dados = request.json or {}
        usuario_digitado = dados.get('username', '').strip()
        senha_digitada = dados.get('password', '').strip()

        if not usuario_digitado or not senha_digitada:
            return jsonify({"status": "erro", "erro": "Preencha todos os campos"}), 400

        # LIMITE DE TENTATIVAS por ORIGEM (ver _tentativas_login). Sem
        # isso, senha curta em rede de escola (onde os alunos têm o mesmo
        # Wi-Fi) é força bruta em segundos — e uma conta de professora dá
        # acesso a documentos de prova pelos relatórios.
        if _excedeu_tentativas():
            log.warning("Login bloqueado por excesso de tentativas de %s", _chave_tentativas())
            return jsonify({"status": "erro", "erro": (
                "Muitas tentativas de entrada deste computador. Espere alguns minutos e "
                "tente de novo, ou procure o Departamento de T.I."
            )}), 429

        usuario = db.autenticar_local(usuario_digitado, senha_digitada)

        if not usuario:
            _registrar_tentativa()
            return jsonify({"status": "erro", "erro": "Usuário ou senha incorretos."}), 401

        _limpar_tentativas()

        # A recusa acontece DEPOIS de conferir a senha, e com mensagem
        # própria: dizer "usuário ou senha incorretos" aqui faria o
        # professor trocar a senha achando que esqueceu.
        if bloqueado_por_modo_desenvolvimento(usuario):
            return jsonify({
                "status": "erro",
                "erro": "O sistema está em manutenção no momento. Procure o Departamento de T.I.",
            }), 403

        return jsonify({
            "status": "sucesso",
            "name": usuario["name"],
            "role": usuario["role"],
            "isSuperAdmin": usuario["isSuperAdmin"],
            "segmento": usuario.get("segmento"),
            "segmentos": db.normalizar_segmentos(usuario.get("segmentos") or usuario.get("segmento")),
            "token": gerar_token_sessao(usuario),
        })

    except Exception:
        # O traceback vai para o log; o cliente recebe mensagem genérica.
        # Descartar a exceção deixava um bug em produção indiagnosticável.
        log.exception("falha em /api/login")
        return jsonify({"status": "erro", "erro": "Erro interno no servidor."}), 500


@app.route('/api/login/google', methods=['POST'])
def login_google_backend():
    try:
        dados = request.json or {}
        token_jwt = dados.get('token')

        if not token_jwt:
            return jsonify({"status": "erro", "erro": "Token de autenticação ausente."}), 400

        # VALIDAÇÃO GOOGLE: clock_skew=60 previne erros de relógio desincronizado
        id_info = id_token.verify_oauth2_token(
            token_jwt,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=60
        )

        email_google = id_info.get('email', '').lower().strip()
        nome_google = id_info.get('name', 'Usuário Workspace')

        usuario = db.obter_ou_cadastrar_workspace(email_google, nome_google)

        # Mesmo bloqueio do login local: em modo de desenvolvimento só o
        # administrador-mestre entra — esta rota não pode ser a porta dos
        # fundos que ignora a manutenção.
        if bloqueado_por_modo_desenvolvimento(usuario):
            return jsonify({
                "status": "erro",
                "erro": "O sistema está em manutenção no momento. Procure o Departamento de T.I.",
            }), 403

        return jsonify({
            "status": "sucesso",
            "name": usuario["name"],
            "role": usuario["role"],
            "isSuperAdmin": usuario["isSuperAdmin"],
            "segmento": usuario.get("segmento"),
            "segmentos": db.normalizar_segmentos(usuario.get("segmentos") or usuario.get("segmento")),
            "token": gerar_token_sessao(usuario),
        })

    except ValueError as e:
        # O motivo exato (que descreve a validação interna do token) fica
        # no log; ao cliente vai uma mensagem genérica. Detalhe de
        # validação de credencial na resposta ajuda quem está tentando
        # adivinhar, não quem está tentando entrar.
        log.warning("Login Google recusado: %s", e)
        return jsonify({"status": "erro", "erro": "Não foi possível entrar com a conta Google."}), 401
    except Exception:
        log.exception("falha em /api/login/google")
        return jsonify({"status": "erro", "erro": "Erro interno no servidor."}), 500


@app.route('/api/registrar', methods=['POST'])
def registrar_conta():
    """Auto-cadastro de professor. A conta é SEMPRE criada como
    COORDENADOR, sem privilégio de administrador — promover alguém a TI é
    decisão do Departamento, feita no painel de usuários. Em caso de
    sucesso já devolve o token, deixando a pessoa logada na hora."""
    try:
        # Auto-cadastro sai sempre como COORDENADOR, que em modo de
        # desenvolvimento não entra. Criar a conta para depois barrar o
        # login seria só uma forma pior de dizer não.
        if horario_impressao.modo_desenvolvimento():
            return jsonify({
                "status": "erro",
                "erro": "O sistema está em manutenção no momento. Procure o Departamento de T.I.",
            }), 403

        # O auto-cadastro entra no MESMO limite de tentativas do login:
        # sem isso, sobrava um caminho sem limite nenhum para criar contas
        # em massa (e para descobrir quais nomes de usuário já existem,
        # pela mensagem de conflito).
        if _excedeu_tentativas():
            log.warning("Auto-cadastro bloqueado por excesso de tentativas de %s",
                        _chave_tentativas())
            return jsonify({"status": "erro", "erro": (
                "Muitas tentativas deste computador. Espere alguns minutos ou procure "
                "o Departamento de T.I."
            )}), 429
        _registrar_tentativa()

        # Com ACALANTO_AUTOCADASTRO=fechado, criar conta é atribuição do
        # T.I. — a rota recusa em vez de deixar qualquer um que alcance o
        # servidor (a rede inteira do colégio, inclusive celular de aluno)
        # abrir uma conta e imprimir.
        if AUTOCADASTRO != "aberto":
            return jsonify({
                "status": "erro",
                "erro": ("O cadastro de novas contas é feito pelo Departamento de T.I. "
                         "Procure a equipe para liberar seu acesso."),
            }), 403

        dados = request.json or {}
        username = dados.get('username', '').strip()
        senha = dados.get('password', '')
        nome = dados.get('name', '').strip()
        # Opcional: só pré-preenche o formulário de envio da pessoa. Virar
        # COORDENACAO (supervisiona o segmento) é decisão do Departamento,
        # feita no painel — o auto-cadastro nunca concede supervisão.
        # Aceita 'segmentos' (lista) ou 'segmento' (código único); a
        # normalização é a mesma de criar_usuario_local.
        segmento = dados.get('segmentos') if dados.get('segmentos') is not None else dados.get('segmento')

        if not username or not senha or not nome:
            return jsonify({"status": "erro", "erro": "Preencha nome, usuário e senha."}), 400
        if len(senha) < SENHA_MINIMA:
            return jsonify({"status": "erro",
                            "erro": f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres."}), 400

        ok, msg = db.criar_usuario_local(username, senha, nome,
                                         role=db.ROLE_COORDENADOR, super_admin=0,
                                         segmento=segmento)
        if not ok:
            return jsonify({"status": "erro", "erro": msg}), 409

        usuario = db.autenticar_local(username, senha)
        return jsonify({
            "status": "sucesso",
            "name": usuario["name"],
            "role": usuario["role"],
            "isSuperAdmin": usuario["isSuperAdmin"],
            "segmento": usuario.get("segmento"),
            "segmentos": db.normalizar_segmentos(usuario.get("segmentos") or usuario.get("segmento")),
            "token": gerar_token_sessao(usuario),
        })
    except Exception:
        log.exception("falha em /api/registrar")
        return jsonify({"status": "erro", "erro": "Erro interno no servidor."}), 500

@app.route('/api/senha', methods=['POST'])
def trocar_propria_senha():
    """Troca a senha da própria conta.

    Diferente do reset do T.I. (/api/admin/usuarios/<username>/senha), aqui
    a SENHA ATUAL é obrigatória. Sem isso, um token roubado ou uma sessão
    esquecida aberta bastaria para tomar a conta — o token sozinho não pode
    valer como autorização para trocar a credencial que ele representa.

    A conta alterada é sempre a do token (`uid`); não existe parâmetro de
    usuário, justamente para não virar um caminho de trocar a senha alheia.

    Trocar a senha DERRUBA as sessões já abertas daquela conta: o
    token_version é incrementado no banco e os tokens antigos deixam de
    bater (ver usuario_autenticado). Quem trocou a senha porque desconfia
    que alguém a tem precisa que isso valha na hora, não em 12h.
    """
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    if sessao.get("metodo") != "local":
        return jsonify({"erro": "Esta conta não usa senha do sistema."}), 400

    dados = request.json or {}
    atual = dados.get('senha_atual', '')
    nova = dados.get('nova_senha', '')

    if not atual or not nova:
        return jsonify({"erro": "Preencha a senha atual e a nova."}), 400
    if len(nova) < SENHA_MINIMA:
        return jsonify({"erro": f"A nova senha precisa ter pelo menos {SENHA_MINIMA} caracteres."}), 400
    if nova == atual:
        return jsonify({"erro": "A nova senha é igual à atual."}), 400

    uid = sessao.get("uid") or ""
    if not db.autenticar_local(uid, atual):
        return jsonify({"erro": "Senha atual incorreta."}), 403

    ok, msg = db.redefinir_senha_local(uid, nova)
    if not ok:
        return jsonify({"erro": msg}), 400

    # A troca derrubou este próprio token (token_version subiu). Devolvemos
    # um token novo para a pessoa continuar trabalhando sem refazer o login
    # — as OUTRAS sessões da conta é que caem, que é o objetivo.
    usuario = db.autenticar_local(uid, nova)
    resposta = {"status": "sucesso"}
    if usuario:
        resposta["token"] = gerar_token_sessao(usuario)
    return jsonify(resposta)


# -------------------------------------------------------------------------
# ROTAS DA FILA E UPLOADS
# -------------------------------------------------------------------------
@app.route('/api/fila', methods=['GET'])
def api_fila():
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    user_name = sessao["name"]
    role_real = sessao["role"]
    super_admin = bool(sessao.get("isSuperAdmin"))

    # O Admin pode pedir para visualizar como qualquer cargo (Coordenador,
    # Diretoria, Coordenação ou TI); esse parâmetro é só uma PREFERÊNCIA de
    # visualização, nunca uma promoção: o papel real continua vindo do
    # token assinado.
    modo_visualizacao = request.args.get('view_mode', role_real).strip().upper()

    if super_admin and modo_visualizacao in db.PAPEIS_VALIDOS:
        role_em_uso = modo_visualizacao
    else:
        role_em_uso = role_real

    # O escopo é decidido aqui, no servidor, com base no token — o cliente
    # não tem como ampliar a própria visão. Usa o segmento REAL da sessão
    # (não dá pra "prever como" um segmento específico, só como um papel).
    escopo, segmentos_escopo = escopo_de_visao({**sessao, "role": role_em_uso})

    conn = db.get_connection()
    cursor = conn.cursor()

    colunas = ("id, professor_nome, materia, turma, arquivo_nome, copias, "
               "paginas, folhas, status, criado_em, impresso_em, segmento, "
               "erro_motivo, usuario_uid, cor, frente_verso, acabamento")
    if escopo == "TUDO":
        cursor.execute(f"SELECT {colunas} FROM pedidos ORDER BY id DESC")
        linhas_banco = cursor.fetchall()
    elif escopo == "SEGMENTO":
        # A coordenação pode cobrir mais de um segmento — a lista vem do
        # escopo (nunca vazia neste ramo) e vira um IN com placeholders.
        #
        # A UNIÃO com os próprios pedidos é essencial: uma coordenadora que
        # dá aula fora do segmento que supervisiona (ou que manda algo de
        # uso próprio, sem segmento) não via o PRÓPRIO envio na fila — e,
        # sem vê-lo, também não podia cancelá-lo. Ninguém deve perder de
        # vista o que ele mesmo mandou imprimir.
        marcadores = ",".join("?" for _ in segmentos_escopo)
        cursor.execute(
            f"SELECT {colunas} FROM pedidos "
            f"WHERE segmento IN ({marcadores}) OR usuario_uid = ? "
            "ORDER BY id DESC",
            (*segmentos_escopo, sessao.get("uid", "")),
        )
        linhas_banco = cursor.fetchall()
    else:  # PROPRIO
        # Filtra pela CONTA (uid), não pelo nome: nomes completos podem se
        # repetir, e dois homônimos não devem ver os pedidos um do outro.
        # Pedidos de antes da coluna usuario_uid existir (NULL) continuam
        # aparecendo pelo nome — melhor um resquício visível ao homônimo do
        # que sumir com o histórico legítimo de alguém.
        cursor.execute(
            f"SELECT {colunas} FROM pedidos "
            "WHERE usuario_uid = ? OR (usuario_uid IS NULL AND professor_nome = ?) "
            "ORDER BY id DESC",
            (sessao.get("uid", ""), user_name),
        )
        linhas_banco = cursor.fetchall()

    # POSIÇÃO REAL NA FILA DA ESCOLA. As linhas acima já vieram filtradas
    # pelo escopo: contar a posição dentro delas diria "1º" para o primeiro
    # pendente DO PROFESSOR, mesmo com 30 pedidos de outras pessoas na
    # frente. O professor leria "1º da fila", esperaria o papel em minutos,
    # e ele sairia em uma hora — o sistema prometendo o que não cumpre.
    # A ordem aqui é a ordem real de consumo do agente (id ASC).
    cursor.execute("SELECT id FROM pedidos WHERE status = 'Pendente' ORDER BY id ASC")
    ordem_global = {l["id"]: i + 1 for i, l in enumerate(cursor.fetchall())}
    total_pendentes_global = len(ordem_global)

    conn.close()

    # Estas contagens descrevem O QUE ESTA PESSOA VÊ (o escopo dela) — o
    # número da escola inteira é o 'pendentes_global' abaixo.
    pendentes = sum(1 for l in linhas_banco if l["status"] == "Pendente")
    imprimindo = sum(1 for l in linhas_banco if l["status"] == "Imprimindo")
    concluidos = sum(1 for l in linhas_banco if l["status"] == "Concluído")
    cancelados = sum(1 for l in linhas_banco if l["status"] == "Cancelado")

    uid_sessao = (sessao.get("uid") or "").strip().lower()
    pedidos_lista = []

    for linha in linhas_banco:
        status_job = linha["status"]
        posicao_global = ordem_global.get(linha["id"]) if status_job == 'Pendente' else None

        # As opções vão NORMALIZADAS (booleanos) e não como o texto cru: o
        # banco tem as duas formas históricas ("FrenteVerso" e "Frente e
        # Verso"), e quem sabe interpretar isso é o módulo compartilhado —
        # não o navegador. Antes o front fabricava valores fixos aqui.
        colorida, grampeada, duplex = interpretar_opcoes(
            linha["cor"], linha["acabamento"], linha["frente_verso"])

        pedidos_lista.append({
            "id": linha["id"],
            "remetente": linha["professor_nome"],
            "materia": linha["materia"],
            "turma": linha["turma"],
            # Campo antigo, mantido para não quebrar quem já lia a fila. O
            # front usa os dois campos acima: separar de volta pelo " — "
            # falhava se o próprio texto de "Outro" trouxesse o separador.
            "materia_turma": f"{linha['materia']} — {linha['turma']}",
            "arquivo": linha["arquivo_nome"],
            "copias": linha["copias"],
            "paginas": linha["paginas"],
            # FOLHAS DE PAPEL (ver opcoes_impressao.folhas_do_pedido) —
            # unidade diferente de "impressões", que é por face.
            "folhas": linha["folhas"],
            # Opções do pedido, para a tela explicar a conta das folhas: sem
            # saber que é frente e verso, "5 páginas × 12 cópias = 36
            # folhas" parece errado (o intuitivo seria 60).
            "duplex": duplex,
            "colorida": colorida,
            "grampeada": grampeada,
            # Posição na fila da ESCOLA, com o total, para o front escrever
            # "3º de 27" em vez de um "3º" ambíguo.
            "posicao": f"{posicao_global}º" if posicao_global else "-",
            "posicao_global": posicao_global,
            "total_na_fila": total_pendentes_global,
            "status": status_job,
            "criado_em": linha["criado_em"],
            "impresso_em": linha["impresso_em"],
            # Motivo do erro em português ("a impressora estava sem papel"),
            # para o professor saber se reenvia, espera ou liga para alguém.
            "erro_motivo": linha["erro_motivo"],
            "segmento": linha["segmento"],
            "segmento_rotulo": db.ROTULOS_SEGMENTO.get(linha["segmento"], "Não definido"),
            # O front só oferece "Cancelar" onde o servidor de fato aceita:
            # pedido do próprio remetente e ainda na fila.
            "cancelavel": (
                status_job == "Pendente"
                and bool(uid_sessao)
                and (linha["usuario_uid"] or "").strip().lower() == uid_sessao
            ),
        })

    return jsonify({
        "estatisticas": {
            "pendentes": pendentes,
            "imprimindo": imprimindo,
            "concluidos": concluidos,
            "cancelados": cancelados,
            # Fila da escola inteira, independente do escopo de quem pediu.
            "pendentes_global": total_pendentes_global,
        },
        "pedidos": pedidos_lista,
        # O front usa isso pra deixar o escopo em vigor explícito no título
        # ("Fila — Fundamental I" em vez de só "Fila de Impressão") — a
        # coordenadora de segmento precisa saber, sem adivinhar, que não
        # está vendo a escola inteira. 'segmento' (único) fica preenchido só
        # quando o escopo cobre um segmento; com vários, o que descreve o
        # recorte é 'segmentos' + o rótulo já juntado.
        "escopo": {
            "tipo": escopo,
            "segmento": segmentos_escopo[0] if segmentos_escopo and len(segmentos_escopo) == 1 else None,
            "segmentos": segmentos_escopo or [],
            "segmento_rotulo": db.rotulo_segmentos(segmentos_escopo),
        },
    })


@app.route('/api/enviar', methods=['POST'])
def api_enviar():
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    # O remetente é SEMPRE quem está logado (vem do token), nunca o que o
    # navegador diz na requisição — assim ninguém imprime no nome de outro.
    user_name = sessao["name"]
    user_uid = sessao.get("uid", "")
    user_metodo = sessao.get("metodo", "")
    user_role = sessao.get("role", "")
    eh_diretoria = user_role in db.PAPEIS_DIRETORIA

    cor = request.form.get('cor', '')
    frente_verso = request.form.get('frente_verso', '')
    acabamento = request.form.get('acabamento', '')
    arquivo = request.files.get('arquivo')

    if eh_diretoria:
        # Formulário da Diretoria: um único campo de contexto ("assunto").
        # A "turma" passa a guardar a ÁREA do cargo (Administrativa/
        # Pedagógica), definida pelo servidor a partir do token — o cliente
        # não escolhe a própria área.
        materia = request.form.get('assunto', '').strip()
        turma = db.area_da_diretoria(user_role)
        if not materia:
            return jsonify({"erro": "Informe o assunto do documento."}), 400
        # Diretoria não tem segmento — os envios institucionais ficam sem
        # classificação (NULL), visíveis a T.I., Diretoria e Coordenação
        # Geral, mas não às coordenadoras de segmento.
        segmento_pedido = None
    else:
        # Formulário do coordenador: matéria + turma escolhidos em caixas de
        # seleção. Quem valida é o servidor — a caixa restringe a tela, mas
        # nada impede o navegador de enviar outro valor. Os DOIS campos
        # aceitam também o texto da opção "Outro" (matéria: capa de
        # avaliação, simulado; turma: uso próprio, reunião de pais...), já
        # limpo e limitado por normalizar_*.
        materia = db.normalizar_materia(request.form.get('materia', ''))
        turma = db.normalizar_turma(request.form.get('turma', ''))
        if not turma:
            return jsonify({"erro": "Marque a turma ou descreva o destino em “Outro”."}), 400
        # "Administrativa"/"Pedagógica" são a marca dos envios institucionais
        # da Diretoria (a área vem do cargo, nunca do formulário). Com a
        # turma aceitando texto livre, um professor poderia digitá-las e o
        # pedido ficaria idêntico a um documento da Diretoria na fila.
        if turma.casefold() in {a.casefold() for a in db.AREAS_INSTITUCIONAIS}:
            return jsonify({"erro": "Esse destino é reservado aos envios da Diretoria."}), 400
        if not materia:
            return jsonify({"erro": "Selecione a matéria na lista."}), 400

        # Segmento do PEDIDO (não da pessoa): o professor escolhe a cada
        # envio, porque quem dá aula em mais de um segmento não tem um
        # valor fixo que sirva sempre. Se vier vazio ou fora da lista, cai
        # no segmento cadastrado da conta — mas SÓ quando a conta tem
        # exatamente um: com vários cadastrados não existe "o" segmento
        # para presumir, e o pedido fica sem segmento (NULL) — nunca
        # inventamos um valor.
        segmento_form = (request.form.get('segmento') or '').strip().upper()
        segmentos_conta = db.normalizar_segmentos(sessao.get("segmentos") or sessao.get("segmento"))
        if segmento_form in db.SEGMENTOS_VALIDOS:
            segmento_pedido = segmento_form
        elif len(segmentos_conta) == 1:
            segmento_pedido = segmentos_conta[0]
        elif len(segmentos_conta) > 1:
            # Conta que atende mais de um segmento e não escolheu: RECUSAR,
            # não aceitar sem classificação. Um pedido com segmento NULL não
            # aparece errado — ele simplesmente não aparece para nenhuma
            # coordenação, e o professor não recebia aviso nenhum. Como quem
            # tem vários segmentos é justamente quem mais esquece esse
            # campo, o buraco acontecia onde mais doía.
            return jsonify({"erro": (
                "Selecione o segmento deste envio. Sua conta atende mais de um "
                "segmento, então o sistema não pode escolher por você."
            )}), 400
        else:
            segmento_pedido = None

    try:
        copias = int(request.form.get('copias', 1))
    except (TypeError, ValueError):
        return jsonify({"erro": "Informe o número de cópias (apenas números)."}), 400

    if copias < 1:
        return jsonify({"erro": "Informe pelo menos 1 cópia."}), 400

    if not arquivo:
        return jsonify({"erro": "Escolha o arquivo PDF a imprimir."}), 400

    # Validação do arquivo NO SERVIDOR (o limite de tamanho já é garantido
    # por MAX_CONTENT_LENGTH). O critério é extensão + os primeiros bytes
    # ("%PDF-"), que o navegador não tem como forjar.
    #
    # O mimetype declarado NÃO entra no critério: ele é escolhido pelo
    # navegador, e envio de celular Android, alguns clientes de e-mail e
    # arquivos vindos do Drive chegam como "application/octet-stream". O PDF
    # é válido, os bytes conferem, e o sistema recusava com uma mensagem que
    # a professora não tinha como interpretar. Fica como sinal de log.
    nome_original = secure_filename(arquivo.filename)
    conteudo_pdf = arquivo.read()

    eh_pdf = (
        nome_original.lower().endswith(".pdf")
        and conteudo_pdf[:5] == b"%PDF-"
    )
    if not eh_pdf:
        return jsonify({"erro": (
            "Este arquivo não é um PDF. Se ele estiver em Word, use "
            "“Salvar como → PDF” e envie de novo."
        )}), 400
    if arquivo.mimetype != "application/pdf":
        log.info("PDF aceito com mimetype '%s' (arquivo '%s') — bytes conferem.",
                 arquivo.mimetype, nome_original)

    # LEITURA ÚNICA DO PDF: páginas, "está cifrado?" e "dá para ler?" saem
    # daqui. É a parte cara do envio (até 50 MB), então o resultado segue
    # para o teto de folhas e para o pedido — sem reabrir o arquivo.
    analise = db.analisar_pdf(conteudo_pdf)
    if analise["cifrado"]:
        # PDF protegido por senha: o SumatraPDF não imprime, e com -silent
        # ele não reclama — o pedido terminaria "Concluído" sem papel algum.
        # Este é o caso que vale recusar, porque a falha é garantida.
        return jsonify({"erro": (
            "Este PDF está protegido por senha e não pode ser impresso. "
            "Salve uma cópia sem proteção e envie novamente."
        )}), 400

    total_paginas = analise["paginas"]
    folhas = folhas_do_pedido(total_paginas, copias, frente_verso) if total_paginas else None

    # PDF que o pypdf não conseguiu ler NÃO é recusado. A biblioteca é mais
    # exigente que a impressora: existe PDF levemente malformado que o
    # SumatraPDF imprime sem reclamar, e recusar tudo o que o pypdf estranha
    # reintroduziria a rejeição indevida que queremos evitar. O preço é não
    # saber as folhas — então o teto passa a ser conferido pelas cópias, que
    # é o piso garantido (1 folha por cópia, no mínimo), e o caso fica
    # registrado no log para o T.I. conseguir investigar depois.
    if total_paginas is None:
        log.warning("Pedido de %s: não foi possível contar páginas de '%s' "
                    "(PDF aceito; teto conferido só pelas cópias).", user_uid, nome_original)

    piso_folhas = folhas if folhas is not None else copias

    # TETO DE FOLHAS POR ENVIO. A conta é em folhas de PAPEL, não em
    # páginas: uma apostila de 8 páginas em frente e verso × 60 cópias são
    # 240 folhas, não 480 — recusar por "480" seria rejeição indevida, com
    # um número que a professora não teria como interpretar.
    if MAX_FOLHAS_POR_PEDIDO > 0 and piso_folhas > MAX_FOLHAS_POR_PEDIDO:
        if folhas is not None:
            detalhe_conta = f"({total_paginas} páginas × {copias} cópias)"
        else:
            detalhe_conta = f"({copias} cópias)"
        return jsonify({"erro": (
            f"Este pedido usaria {piso_folhas} folhas de papel {detalhe_conta} "
            f"e o limite por envio é {MAX_FOLHAS_POR_PEDIDO}. "
            f"Reduza as cópias, divida em mais de um envio, ou procure o "
            f"Departamento de T.I. para tiragens maiores."
        )}), 400

    # COTA mensal em folhas (se habilitada). Bloqueia ANTES de gravar, então
    # nada entra na fila à toa.
    if LIMITE_MENSAL_FOLHAS > 0 and user_uid:
        ja_usadas = db.consumo_mensal_folhas(user_uid, datetime.now(FUSO_HORARIO).strftime("%Y-%m"))
        if ja_usadas + piso_folhas > LIMITE_MENSAL_FOLHAS:
            restante = max(0, LIMITE_MENSAL_FOLHAS - ja_usadas)
            return jsonify({"erro": (
                f"Cota mensal de {LIMITE_MENSAL_FOLHAS} folhas excedida. "
                f"Este envio precisa de {piso_folhas} e você tem {restante} disponível(is) "
                f"neste mês. Fale com o Departamento de T.I."
            )}), 403

    # ENVIO DUPLICADO: mesmo arquivo, mesma conta, poucos minutos atrás.
    # Cobre o caso clássico da página que demorou e da professora que
    # clicou de novo — sairia tudo em dobro. O hash já existe de graça.
    # 'confirmar_duplicado' é o "enviar mesmo assim" da tela.
    hash_pdf = hashlib.sha256(conteudo_pdf).hexdigest()
    if not request.form.get("confirmar_duplicado"):
        recente = db.pedido_recente_igual(user_uid, hash_pdf, minutos=10)
        if recente:
            return jsonify({
                "erro": "duplicado",
                "mensagem": (
                    f"Você enviou este mesmo arquivo há {recente['minutos']} minuto(s) "
                    f"(protocolo IMP-{recente['id']:04d}, situação: {recente['status']}). "
                    f"Deseja enviar mesmo assim?"
                ),
                "pedido_existente": recente["id"],
            }), 409

    # O PDF vai direto para o banco (como BLOB), não para um caminho em
    # disco — no Discloud não há garantia de que um arquivo salvo em
    # disco sobreviva a um redeploy ou reinício do container. A criação do
    # pedido já carimba o horário, calcula o hash e registra o evento na
    # trilha de auditoria (ver banco_dados).
    pedido_id, paginas, _hash = db.criar_pedido(
        user_name, user_uid, user_metodo, materia, turma, copias, cor,
        frente_verso, acabamento, nome_original, conteudo_pdf,
        segmento=segmento_pedido, paginas=total_paginas, folhas=folhas
    )
    log.info("Pedido #%s criado por %s (%s): %s pág. × %s cópias = %s folhas.",
             pedido_id, user_name, user_uid, total_paginas, copias, folhas)

    # Note que NÃO chamamos mais a impressão por aqui — quem imprime agora
    # é o agente local, consultando as rotas abaixo. Devolvemos o protocolo
    # (o ID do pedido) e os dados que servem de comprovante ao professor.
    return jsonify({
        "status": "sucesso",
        "mensagem": mensagem_para_envio(),
        "protocolo": f"IMP-{pedido_id:04d}",
        "pedido_id": pedido_id,
        "paginas": paginas,
        "folhas": folhas,
    })


@app.route('/api/pedido/<int:pedido_id>/cancelar', methods=['POST'])
def api_cancelar_pedido(pedido_id):
    """Cancela um pedido do PRÓPRIO remetente, e só enquanto ele ainda está
    na fila. Sem isso, a professora que anexou o PDF errado ou digitou 300
    em vez de 30 não tinha o que fazer além de ligar para o T.I. e torcer
    para chegar antes do agente — em ambiente escolar, isso é papel e
    dinheiro.

    Quem perde a corrida com o agente recebe 409 e uma explicação, não um
    cancelamento falso que deixaria o papel sair de qualquer forma."""
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    ok, motivo = db.cancelar_pedido_se_dono(pedido_id, sessao.get("uid", ""),
                                            ator=sessao.get("name"))
    if not ok:
        # 404 para "não é seu"/"não existe" — não confirmamos a existência
        # de pedido de outra pessoa. 409 para "já saiu da fila".
        codigo = 409 if "impressão" in (motivo or "") else 404
        return jsonify({"erro": motivo}), codigo

    log.info("Pedido #%s cancelado por %s.", pedido_id, sessao.get("uid"))
    return jsonify({"status": "sucesso"})


# -------------------------------------------------------------------------
# ROTAS DO AGENTE DE IMPRESSÃO (rodando no computador do colégio)
# -------------------------------------------------------------------------
@app.route('/api/agente/pendentes', methods=['GET'])
def agente_pendentes():
    """Pedidos aguardando impressão, do mais antigo para o mais novo.

    O LOTE É LIMITADO de propósito. Se 200 pedidos se acumularem durante a
    noite, devolver os 200 de uma vez faria a Konica ficar inutilizável por
    horas para quem precisasse de uma cópia urgente às 08:00. O agente
    volta a cada 15 segundos e pega o próximo lote: a vazão é a mesma, mas
    a fila respira e um pedido novo e pequeno não fica preso atrás de 200
    antigos."""
    if not verificar_chave_agente():
        return jsonify({"erro": "Não autorizado"}), 401

    # Cada chamada do agente é também um sinal de vida — não precisa de
    # rota extra para o caso normal (ver /api/agente/heartbeat, que serve
    # aos ciclos em que ele não busca nada, fora do horário).
    db.registrar_heartbeat()

    limite = max(1, min(ler_int("ACALANTO_LOTE_AGENTE", 20), 200))
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, professor_nome, materia, turma, copias, cor, frente_verso, acabamento
        FROM pedidos WHERE status = 'Pendente' ORDER BY id ASC LIMIT ?
    ''', (limite,))
    pedidos = [dict(linha) for linha in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) FROM pedidos WHERE status = 'Pendente'")
    total = cursor.fetchone()[0]
    conn.close()

    return jsonify({"pedidos": pedidos, "total_pendentes": total, "lote": limite})


@app.route('/api/agente/heartbeat', methods=['POST'])
def agente_heartbeat():
    """Sinal de vida do agente, mandado a cada ciclo — inclusive fora do
    horário de impressão, quando ele não busca pedido nenhum.

    É o que permite ao sistema dizer "a impressora está fora do ar desde
    14:32" em vez de deixar os pedidos acumulando com todo mundo achando
    que está tudo bem. Esse era o único modo de falha do sistema sem
    nenhum tratamento — e o mais provável de todos."""
    if not verificar_chave_agente():
        return jsonify({"erro": "Não autorizado"}), 401
    return jsonify({"status": "sucesso", "registrado_em": db.registrar_heartbeat()})


@app.route('/api/agente/arquivo/<int:pedido_id>', methods=['GET'])
def agente_arquivo(pedido_id):
    if not verificar_chave_agente():
        return jsonify({"erro": "Não autorizado"}), 401

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT arquivo_conteudo, arquivo_purgado FROM pedidos WHERE id = ?', (pedido_id,))
    linha = cursor.fetchone()
    conn.close()

    if linha and linha["arquivo_purgado"]:
        # O registro existe, mas o conteúdo já foi descartado pela retenção.
        return jsonify({"erro": "Arquivo expirado pela política de retenção"}), 410

    if not linha or linha["arquivo_conteudo"] is None:
        return jsonify({"erro": "Arquivo não encontrado"}), 404

    return Response(linha["arquivo_conteudo"], mimetype="application/pdf")


@app.route('/api/agente/status/<int:pedido_id>', methods=['POST'])
def agente_atualizar_status(pedido_id):
    if not verificar_chave_agente():
        return jsonify({"erro": "Não autorizado"}), 401

    db.registrar_heartbeat()
    dados = request.json or {}
    novo_status = dados.get("status")
    # Motivo, em português, para o professor ler quando der erro.
    detalhe = (dados.get("detalhe") or "").strip()[:200] or None

    if novo_status not in ("Imprimindo", "Concluído", "Erro"):
        return jsonify({"erro": "Status inválido"}), 400

    # Identificador da reserva, gerado pelo agente para ESTA tentativa de
    # impressão. É o que torna a reserva idempotente (ver abaixo).
    reserva = (dados.get("reserva") or "").strip()[:64] or None

    if novo_status == "Imprimindo":
        # RESERVA ATÔMICA E IDEMPOTENTE. Atômica: o pedido só sai de
        # 'Pendente' uma vez, então um segundo agente recebe 409 e pula, em
        # vez de imprimir a mesma coisa de novo. Idempotente: se a resposta
        # desta chamada se perder na rede, a retentativa do MESMO agente
        # (mesmo identificador) recebe 200 — sem isso o agente desistia e o
        # pedido congelava em 'Imprimindo' sem nada ser impresso.
        resultado = db.reservar_pedido_para_impressao(pedido_id, reserva=reserva)
        if resultado in ("reservado", "sua"):
            return jsonify({"status": "sucesso", "reserva": resultado})
        if resultado == "inexistente":
            return jsonify({"erro": "Pedido não encontrado"}), 404
        log.warning("Reserva recusada para #%s — outro agente ou fora da fila.", pedido_id)
        return jsonify({"erro": "Pedido já reservado por outro agente ou fora da fila"}), 409

    # 'Concluído'/'Erro' SÓ valem para quem tem o pedido reservado. Sem
    # isso, um agente atrasado (ou uma retentativa antiga) podia marcar
    # como concluído um pedido que outro agente já estava imprimindo, ou
    # ressuscitar um pedido cancelado pelo professor.
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, reservado_por FROM pedidos WHERE id = ?", (pedido_id,))
    linha = cursor.fetchone()
    conn.close()
    if not linha:
        return jsonify({"erro": "Pedido não encontrado"}), 404
    if linha["status"] != "Imprimindo":
        log.warning("Confirmação '%s' recusada para #%s: status atual é '%s'.",
                    novo_status, pedido_id, linha["status"])
        return jsonify({
            "erro": f"Este pedido não está em impressão (está '{linha['status']}').",
            "status_atual": linha["status"],
        }), 409
    if reserva and linha["reservado_por"] and linha["reservado_por"] != reserva:
        log.warning("Confirmação '%s' recusada para #%s: reserva de outro agente.",
                    novo_status, pedido_id)
        return jsonify({"erro": "Este pedido está reservado por outro agente."}), 409

    # Carimba o horário e registra na auditoria que foi o AGENTE quem mudou
    # o status (ator="agente"). 'Concluído' grava impresso_em; 'Erro' grava
    # o motivo, que a fila mostra ao professor.
    encontrado = db.atualizar_status(pedido_id, novo_status, ator="agente",
                                     detalhe_extra=detalhe)
    if not encontrado:
        return jsonify({"erro": "Pedido não encontrado"}), 404

    return jsonify({"status": "sucesso"})


# -------------------------------------------------------------------------
# ROTAS DE PRESTAÇÃO DE CONTAS (somente Departamento de T.I.)
# -------------------------------------------------------------------------
def sessao_ti():
    """Retorna a sessão se o usuário logado for realmente do TI; senão
    None. O papel vem do token assinado — não dá para forjar pela URL."""
    sessao = usuario_autenticado()
    if not sessao or sessao.get("role") != db.ROLE_TI:
        return None
    return sessao


def _pode_ver_relatorio(sessao, tipo):
    """Quem pode ver cada relatório:
      - TI: todos.
      - Diretor Administrativo: só 'custos' (cópias P&B × colorida).
      - Diretora Pedagógica: só 'materias' (o que cada docente envia).
      - COORDENACAO: só 'consumo' (por professor) — é o único tipo que já é
        "por professor", travado no próprio segmento em api_relatorio().
        Uma COORDENACAO com segmento NULL/inválido cai em escopo PROPRIO e
        é barrada logo depois, mesmo passando por aqui.
    Edição/gestão continua exclusiva do TI."""
    role = sessao.get("role")
    if role == db.ROLE_TI:
        return True
    if tipo == "custos" and role == db.ROLE_DIRETOR_ADM:
        return True
    if tipo == "materias" and role == db.ROLE_DIRETORA_PED:
        return True
    if tipo == "consumo" and role == db.ROLE_COORDENACAO:
        return True
    return False


def _sanitizar_nome_arquivo(texto):
    """Deixa um texto livre seguro para entrar no nome de um arquivo
    baixado: sem acento, sem espaço, só [A-Za-z0-9_]."""
    sem_acento = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    limpo = re.sub(r'[^A-Za-z0-9]+', '_', sem_acento).strip('_')
    return limpo or "filtro"


_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _data_ou_none(bruto):
    """Aceita só 'YYYY-MM-DD'; qualquer outra coisa vira None (sem filtro)."""
    texto = (bruto or "").strip()
    return texto if _RE_DATA.match(texto) else None


def _celula_csv(valor):
    """Neutraliza injeção de fórmula no CSV: uma célula começando com '=',
    '+', '-' ou '@' abriria como fórmula no Excel/LibreOffice — e nomes de
    professor/matéria 'Outro' são texto digitado por gente. O apóstrofo na
    frente força a célula a ser texto."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@"):
        return "'" + valor
    return valor


def _csv_resposta(cabecalho, linhas, nome_base, data_inicio, data_fim, professor=None, segmento=None):
    """'segmento' aceita um código só ou uma lista (coordenação que cobre
    mais de um segmento) — o cabeçalho e o nome do arquivo refletem todos."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer)

    # Primeira linha: os filtros aplicados. A planilha vai circular fora do
    # sistema (e-mail, pendrive) e precisa ser autoexplicativa sozinha.
    segmentos = db.normalizar_segmentos(segmento)
    partes_filtro = [f"Período: {data_inicio or 'início'} a {data_fim or 'hoje'}"]
    if professor:
        partes_filtro.append(f"Professor: {professor}")
    if segmentos:
        partes_filtro.append(f"Segmento: {db.rotulo_segmentos(segmentos)}")
    escritor.writerow([" | ".join(partes_filtro)])
    escritor.writerow([])
    escritor.writerow(cabecalho)
    for linha in linhas:
        escritor.writerow([_celula_csv(c) for c in linha])

    periodo = f"{data_inicio or 'inicio'}_a_{data_fim or 'hoje'}"
    nome = nome_base
    if professor:
        nome += f"_{_sanitizar_nome_arquivo(professor)}"
    if segmentos:
        nome += "_" + "_".join(s.lower() for s in segmentos)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nome}_{periodo}.csv"'}
    )


@app.route('/api/relatorio', methods=['GET'])
def api_relatorio():
    """Relatórios de prestação de contas. O parâmetro 'tipo' escolhe qual:
      - 'consumo'  (padrão): por professor — TI e COORDENACAO (só o próprio segmento).
      - 'custos'           : P&B × colorida — TI e Diretor Administrativo.
      - 'materias'         : documentos por matéria — TI e Diretora Pedagógica.
    Aceita data_inicio/data_fim ('YYYY-MM-DD'), professor, segmento e
    formato=json|csv.

    O 'segmento' pedido pelo cliente NUNCA amplia o escopo: para quem tem
    escopo SEGMENTO (COORDENACAO fora de GERAL) ele é sempre travado no(s)
    segmento(s) da própria sessão, ignorando qualquer coisa que a query
    string mande. Só quem já tem escopo TUDO pode pedir um segmento
    específico para estreitar a visão."""
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    tipo = request.args.get("tipo", "consumo").strip().lower()
    # 403 (e não 401) quando a SESSÃO É VÁLIDA mas o cargo não tem acesso a
    # este relatório: o front trata 401 como "sessão expirada" e desloga a
    # pessoa. Uma coordenação sem segmento cadastrado era expulsa do
    # sistema ao abrir Relatórios, em vez de ler "sem permissão".
    if not _pode_ver_relatorio(sessao, tipo):
        return jsonify({"erro": "Seu cargo não tem acesso a este relatório."}), 403

    # Piso de escopo, resolvido do token — o que vem a seguir só pode
    # ESTREITAR esse piso, nunca alargá-lo. escopo "PROPRIO" nunca chega
    # aqui de fato (só COORDENACAO tem tipo liberado por _pode_ver_relatorio
    # sem ser TI/Diretoria, e ela só passou se seu papel bate; mas uma
    # COORDENACAO com segmento inválido cai em PROPRIO e é barrada abaixo,
    # em vez de silenciosamente virar "vê tudo").
    escopo, segmentos_piso = escopo_de_visao(sessao)
    if escopo == "SEGMENTO":
        segmento = segmentos_piso  # lista — pode cobrir mais de um segmento
        segmento_travado = True
    elif escopo == "TUDO":
        segmento_pedido = request.args.get("segmento", "").strip().upper()
        segmento = segmento_pedido if segmento_pedido in db.SEGMENTOS_VALIDOS else None
        segmento_travado = False
    else:
        # Também 403: a sessão vale, o escopo é que não alcança relatório.
        return jsonify({"erro": (
            "Sua conta não tem um segmento cadastrado, então não há relatório para "
            "mostrar. Procure o Departamento de T.I."
        )}), 403

    professor = request.args.get("professor", "").strip() or None
    # Datas fora do formato YYYY-MM-DD são descartadas: além de não filtrar
    # nada de útil, elas entrariam cruas no cabeçalho Content-Disposition do
    # CSV (nome do arquivo) — texto arbitrário em cabeçalho HTTP é vetor de
    # injeção.
    data_inicio = _data_ou_none(request.args.get("data_inicio"))
    data_fim = _data_ou_none(request.args.get("data_fim"))
    formato = request.args.get("formato", "json").strip().lower()
    periodo = {"inicio": data_inicio, "fim": data_fim}
    # No JSON, 'segmento' (único) fica preenchido só quando o filtro cobre
    # exatamente um segmento; com vários, quem descreve o recorte é a lista
    # 'segmentos' + 'segmento_rotulo' já juntado (o front exibe direto).
    segmentos_filtro = db.normalizar_segmentos(segmento)
    filtros_aplicados = {
        "professor": professor,
        "segmento": segmentos_filtro[0] if len(segmentos_filtro) == 1 else None,
        "segmentos": segmentos_filtro,
        "segmento_rotulo": db.rotulo_segmentos(segmentos_filtro),
        "segmento_travado": segmento_travado,
    }

    if tipo == "custos":
        dados = db.relatorio_custos(data_inicio, data_fim, professor=professor, segmento=segmento)
        if formato == "csv":
            # As duas métricas convivem de propósito: "impressões" é por
            # face (o que o toner gasta e o contrato da Konica cobra) e
            # "folhas" é papel (o que a escola compra). Trocar uma pela
            # outra em silêncio faria o número que a Diretoria acompanha
            # cair pela metade sem explicação.
            linhas = [[p["professor_nome"], p["copias_pb"], p["copias_cor"],
                       p["folhas_pb"], p["folhas_cor"], p["folhas_pb"] + p["folhas_cor"],
                       p["impressoes_pb"], p["impressoes_cor"],
                       p["impressoes_pb"] + p["impressoes_cor"]] for p in dados["por_professor"]]
            return _csv_resposta(
                ["Professor", "Cópias P&B", "Cópias Colorida",
                 "Folhas P&B", "Folhas Colorida", "Folhas Total",
                 "Impressões P&B", "Impressões Colorida", "Impressões Total"],
                linhas, "relatorio_custos", data_inicio, data_fim,
                professor=professor, segmento=segmento)
        return jsonify({"periodo": periodo, "filtros": filtros_aplicados, **dados})

    if tipo == "materias":
        resultado = db.relatorio_por_materia(data_inicio, data_fim, professor=professor, segmento=segmento)
        documentos = resultado["documentos"]
        if formato == "csv":
            linhas = [[d["materia"], d["professor_nome"], d["arquivo_nome"],
                       d["copias"], d["paginas"], d["criado_em"], d["status"]] for d in documentos]
            return _csv_resposta(
                ["Matéria", "Docente", "Arquivo", "Cópias", "Páginas", "Enviado em", "Status"],
                linhas, "relatorio_materias", data_inicio, data_fim,
                professor=professor, segmento=segmento)
        return jsonify({
            "periodo": periodo,
            "filtros": filtros_aplicados,
            "documentos": documentos,
            "professores_disponiveis": resultado["professores_disponiveis"],
            "totais": {
                "documentos": len(documentos),
                "impressoes": sum((d["paginas"] or 0) * d["copias"] for d in documentos),
                "folhas": sum(d.get("folhas") or 0 for d in documentos),
            },
        })

    # tipo == "consumo" (padrão)
    resultado = db.relatorio_consumo(data_inicio, data_fim, professor=professor, segmento=segmento)
    linhas = resultado["linhas"]
    if formato == "csv":
        return _csv_resposta(
            ["Professor", "Identificador", "Pedidos", "Total de cópias",
             "Total de páginas", "Folhas de papel", "Total de impressões"],
            [[l["professor_nome"], l["usuario_uid"], l["pedidos"], l["total_copias"],
              l["total_paginas"], l["total_folhas"], l["total_impressoes"]] for l in linhas],
            "relatorio_consumo", data_inicio, data_fim,
            professor=professor, segmento=segmento)
    return jsonify({
        "periodo": periodo,
        "filtros": filtros_aplicados,
        "linhas": linhas,
        "professores_disponiveis": resultado["professores_disponiveis"],
        "totais": {
            "impressoes": sum(l["total_impressoes"] for l in linhas),
            "folhas": sum(l["total_folhas"] for l in linhas),
            "copias": sum(l["total_copias"] for l in linhas),
            "pedidos": sum(l["pedidos"] for l in linhas),
        },
    })


@app.route('/api/relatorio/documento/<int:pedido_id>', methods=['GET'])
def api_relatorio_documento(pedido_id):
    """Abre o PDF de um pedido para conferência. Restrito a quem tem escopo
    TUDO (T.I., Diretora Pedagógica, Coordenação Geral) ou, para uma
    COORDENACAO de segmento, aos pedidos do PRÓPRIO segmento — mesma lógica
    da Diretora Pedagógica, aplicada dentro do recorte do segmento.

    O Diretor Administrativo nunca teve acesso a documento (não faz parte
    do trabalho dele conferir o conteúdo enviado) — isso continua valendo
    mesmo ele tendo escopo TUDO na fila, porque são permissões diferentes."""
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401
    if sessao.get("role") == db.ROLE_DIRETOR_ADM:
        return jsonify({"erro": "Não autorizado"}), 401

    escopo, segmentos_piso = escopo_de_visao(sessao)
    if escopo == "PROPRIO":
        return jsonify({"erro": "Não autorizado"}), 401

    arquivo = db.obter_arquivo_pedido(pedido_id)
    if not arquivo:
        return jsonify({"erro": "Arquivo não encontrado"}), 404
    if escopo == "SEGMENTO" and arquivo["segmento"] not in segmentos_piso:
        return jsonify({"erro": "Não autorizado"}), 401
    if arquivo["purgado"]:
        return jsonify({"erro": "Arquivo expirado pela política de retenção"}), 410
    if not arquivo["conteudo"]:
        return jsonify({"erro": "Arquivo não encontrado"}), 404

    return Response(arquivo["conteudo"], mimetype="application/pdf")


@app.route('/api/pedido/<int:pedido_id>/eventos', methods=['GET'])
def api_eventos_pedido(pedido_id):
    """Trilha de auditoria completa de um pedido (quem fez o quê e quando).
    Restrito ao TI."""
    if not sessao_ti():
        return jsonify({"erro": "Não autorizado"}), 401

    return jsonify({"pedido_id": pedido_id, "eventos": db.listar_eventos(pedido_id)})


# -------------------------------------------------------------------------
# ROTAS DE GESTÃO DE USUÁRIOS (somente Departamento de T.I.)
# -------------------------------------------------------------------------
def _pode_administrar_alvo(sessao, username_alvo):
    """Regras de proteção comuns às ações de administração. Devolve uma
    mensagem de erro se a ação não for permitida, ou None se estiver ok."""
    alvo = db.obter_usuario_local(username_alvo)
    if not alvo:
        return "Usuário não encontrado.", None
    # Não deixar ninguém mexer na própria conta (evita auto-lockout/confusão).
    if alvo["username"] == (sessao.get("uid") or "").lower():
        return "Você não pode alterar a própria conta por aqui.", alvo
    # A conta de administrador (super_admin) só pode ser tocada por outro
    # administrador — um TI comum não rebaixa nem remove o admin-mestre.
    if alvo["isSuperAdmin"] and not sessao.get("isSuperAdmin"):
        return "Apenas o administrador-mestre pode alterar essa conta.", alvo
    return None, alvo


@app.route('/api/admin/usuarios', methods=['GET'])
def admin_listar_usuarios():
    if not sessao_ti():
        return jsonify({"erro": "Não autorizado"}), 401
    return jsonify({"usuarios": db.listar_usuarios_locais()})


@app.route('/api/admin/usuarios', methods=['POST'])
def admin_criar_usuario():
    """Cria uma conta diretamente pelo painel (o TI pode pré-cadastrar
    alguém já com o cargo certo, sem esperar o auto-cadastro)."""
    if not sessao_ti():
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.json or {}
    senha = dados.get('password', '')
    role = dados.get('role', db.ROLE_COORDENADOR).strip().upper()
    # 'segmentos' (lista) é a forma nova; 'segmento' (código único) segue
    # aceito. criar_usuario_local normaliza os dois do mesmo jeito.
    segmento = dados.get('segmentos') if dados.get('segmentos') is not None else dados.get('segmento')
    if segmento is not None and (
        not isinstance(segmento, (str, list))
        or (isinstance(segmento, list) and any(not isinstance(i, str) for i in segmento))
    ):
        return jsonify({"erro": "Formato inválido de segmento."}), 400
    if len(senha) < SENHA_MINIMA:
        return jsonify({"erro": f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres."}), 400

    ok, msg = db.criar_usuario_local(
        dados.get('username', ''), senha, dados.get('name', ''),
        role=role, super_admin=0, segmento=segmento
    )
    if not ok:
        return jsonify({"erro": msg}), 409
    return jsonify({"status": "sucesso"})


@app.route('/api/admin/usuarios/<username>/role', methods=['POST'])
def admin_alterar_role(username):
    sessao = sessao_ti()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    erro, _alvo = _pode_administrar_alvo(sessao, username)
    if erro:
        return jsonify({"erro": erro}), 400

    novo_role = (request.json or {}).get('role', '').strip().upper()
    ok, msg = db.atualizar_role_local(username, novo_role)
    if not ok:
        return jsonify({"erro": msg}), 400
    return jsonify({"status": "sucesso"})


@app.route('/api/admin/usuarios/<username>/segmento', methods=['POST'])
def admin_alterar_segmento(username):
    """Define o(s) segmento(s) de uma conta (mesmo padrão de /role acima).
    Aceita 'segmentos' (lista — a conta pode participar de mais de um) ou o
    antigo 'segmento' (código único). Para um professor comum é só o que
    pré-preenche o formulário de envio; para uma COORDENACAO é o que define
    o escopo de visão dela — daí a mesma proteção de _pode_administrar_alvo
    (ninguém mexe na própria conta, um TI comum não mexe na conta
    super_admin)."""
    sessao = sessao_ti()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    erro, _alvo = _pode_administrar_alvo(sessao, username)
    if erro:
        return jsonify({"erro": erro}), 400

    dados = request.json or {}
    novo_segmento = dados.get('segmentos') if dados.get('segmentos') is not None else dados.get('segmento', '')
    # Tipo errado (número, objeto, lista com não-string) vira 400 explícito,
    # não um 500 lá dentro da camada de banco.
    if not isinstance(novo_segmento, (str, list)) or (
        isinstance(novo_segmento, list) and any(not isinstance(i, str) for i in novo_segmento)
    ):
        return jsonify({"erro": "Formato inválido de segmento."}), 400
    ok, msg = db.definir_segmento_usuario_local(username, novo_segmento)
    if not ok:
        return jsonify({"erro": msg}), 400
    return jsonify({"status": "sucesso"})


@app.route('/api/admin/usuarios/<username>/senha', methods=['POST'])
def admin_resetar_senha(username):
    sessao = sessao_ti()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    nova = (request.json or {}).get('password', '')
    if len(nova) < SENHA_MINIMA:
        return jsonify({"erro": f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres."}), 400

    erro, _alvo = _pode_administrar_alvo(sessao, username)
    if erro:
        return jsonify({"erro": erro}), 400

    ok, msg = db.redefinir_senha_local(username, nova)
    if not ok:
        return jsonify({"erro": msg}), 400
    return jsonify({"status": "sucesso"})


@app.route('/api/admin/usuarios/<username>/remover', methods=['POST'])
def admin_remover_usuario(username):
    sessao = sessao_ti()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    erro, _alvo = _pode_administrar_alvo(sessao, username)
    if erro:
        return jsonify({"erro": erro}), 400

    db.remover_usuario_local(username)
    return jsonify({"status": "sucesso"})


if __name__ == '__main__':
    modo_debug = os.environ.get("ACALANTO_DEBUG", "false").lower() == "true"
    # Onde escutar. O padrão 0.0.0.0 (todas as placas de rede) é o que os
    # professores precisam quando o servidor atende direto, como no Windows.
    # Na VM Linux com nginx na frente, ACALANTO_HOST=127.0.0.1 fecha o acesso
    # direto à porta 8080: só o proxy fala com a aplicação.
    host = os.environ.get("ACALANTO_HOST", "0.0.0.0").strip() or "0.0.0.0"
    porta = ler_int("ACALANTO_PORT", 8080)
    if modo_debug:
        app.run(host=host, debug=True, use_reloader=False, port=porta)
    else:
        # PRODUÇÃO: waitress, não o servidor embutido do Flask (que a
        # própria documentação do Flask diz não usar em produção — um
        # upload de 50 MB ocupa a thread e os professores enfileiram atrás
        # dele). waitress é a escolha para Windows; gunicorn não roda aqui.
        try:
            from waitress import serve
            log.info("Servidor (waitress) em http://%s:%s", host, porta)
            # max_request_body_size alinhado ao limite do Flask: sem isso o
            # waitress aceitaria ~1 GB antes de o Flask recusar com 413 —
            # a rede do colégio engoliria o upload inteiro à toa.
            serve(app, host=host, port=porta, threads=8,
                  max_request_body_size=MAX_UPLOAD_BYTES + (1 << 20))
        except ImportError:
            # Sem waitress instalado, seguir subindo é melhor que não subir
            # — mas com aviso, porque é o servidor de desenvolvimento.
            log.warning("waitress não está instalado (pip install waitress) — "
                        "subindo no servidor de desenvolvimento do Flask.")
            app.run(host=host, debug=False, use_reloader=False, port=porta)