import os
import csv
import io
from datetime import datetime, time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import banco_dados as db  # Toda a lógica de usuários, senhas e privilégios
                           # de Admin vive em banco_dados/ — não aqui.
import horario_impressao  # Faixa de horário, compartilhada com o agente.
from horario_impressao import FUSO_HORARIO

# Carrega o arquivo .env (se existir) para dentro de os.environ, ANTES de
# qualquer os.environ.get() abaixo. Sem essa linha, o .env não tem efeito
# nenhum — ele é só um arquivo de texto até alguém ler ele.
load_dotenv()

app = Flask(__name__)

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

# COTA mensal de impressões (páginas × cópias) por usuário. 0 = ilimitado
# (padrão). Quando > 0, /api/enviar recusa o pedido que faria o usuário
# estourar o limite no mês — controle preventivo de consumo.
LIMITE_MENSAL_IMPRESSOES = int(os.environ.get("ACALANTO_LIMITE_MENSAL_IMPRESSOES", "0"))

# RETENÇÃO: depois de quantos dias o conteúdo de um PDF já impresso é
# descartado (mantendo o registro e o hash para auditoria). 0 = nunca
# descartar (padrão). A limpeza roda na inicialização do servidor.
RETENCAO_DIAS = int(os.environ.get("ACALANTO_RETENCAO_DIAS", "0"))

# Horário em que a impressora "aceita" trabalhos. Fora dessa faixa, os
# pedidos ficam represados como Pendente normalmente — o agente local que
# decide não imprimir fora do expediente (ver agente_impressao.py).
# A faixa vem de horario_impressao.py, compartilhado com o agente, e é
# configurável pelo .env (HORARIO_INICIO_IMPRESSAO / HORARIO_FIM_IMPRESSAO).

db.init_db()
horario_impressao.avisar_se_desenvolvimento("app.py")

# Aplica a política de retenção uma vez ao subir o servidor (descarta o
# conteúdo de PDFs antigos já impressos). Para purga contínua, agende um
# reinício periódico ou uma chamada à função em um cron.
if RETENCAO_DIAS > 0:
    _purgados = db.purgar_pdfs_antigos(RETENCAO_DIAS)
    if _purgados:
        print(f"[Retenção] Conteúdo de {_purgados} PDF(s) descartado (> {RETENCAO_DIAS} dias).")


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
    nunca libera por padrão."""
    if not AGENTE_API_KEY:
        return False
    return request.headers.get("Authorization", "") == f"Bearer {AGENTE_API_KEY}"


def gerar_token_sessao(usuario):
    """Cria um token assinado com a identidade do usuário. Esse token é a
    única prova de identidade aceita por /api/fila e /api/enviar — o nome,
    o papel e o identificador único (uid) nunca mais vêm 'soltos' na URL.
    O uid (username local ou e-mail Workspace) é o que amarra cada pedido
    a uma conta específica, sem depender do nome (que pode se repetir)."""
    return _serializador_token.dumps({
        "name": usuario["name"],
        "role": usuario["role"],
        "isSuperAdmin": usuario["isSuperAdmin"],
        "uid": usuario.get("uid", ""),
        "metodo": usuario.get("metodo", ""),
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
    ser ligado, que de outra forma continuariam valendo até expirar."""
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
    return usuario


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
    return jsonify({
        "inicio": inicio.strftime("%H:%M"),
        "fim": fim.strftime("%H:%M"),
        "so_dias_uteis": horario_impressao.so_dias_uteis(),
        "descricao": horario_impressao.descricao(),
        "aberto_agora": horario_impressao.dentro_do_horario(),
        "modo_desenvolvimento": horario_impressao.modo_desenvolvimento(),
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

        usuario = db.autenticar_local(usuario_digitado, senha_digitada)

        if not usuario:
            return jsonify({"status": "erro", "erro": "Usuário ou senha incorretos."}), 401

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
            "token": gerar_token_sessao(usuario),
        })

    except Exception:
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

        return jsonify({
            "status": "sucesso",
            "name": usuario["name"],
            "role": usuario["role"],
            "isSuperAdmin": usuario["isSuperAdmin"],
            "token": gerar_token_sessao(usuario),
        })

    except ValueError as e:
        erro_exato = str(e)
        print(f"Motivo real da rejeição do Google: {erro_exato}")
        return jsonify({"status": "erro", "erro": f"Recusado pelo Google: {erro_exato}"}), 401
    except Exception as e:
        print(f"Erro crítico no servidor durante OAuth: {str(e)}")
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

        dados = request.json or {}
        username = dados.get('username', '').strip()
        senha = dados.get('password', '')
        nome = dados.get('name', '').strip()

        if not username or not senha or not nome:
            return jsonify({"status": "erro", "erro": "Preencha nome, usuário e senha."}), 400
        if len(senha) < 4:
            return jsonify({"status": "erro", "erro": "A senha precisa ter pelo menos 4 caracteres."}), 400

        ok, msg = db.criar_usuario_local(username, senha, nome,
                                         role=db.ROLE_COORDENADOR, super_admin=0)
        if not ok:
            return jsonify({"status": "erro", "erro": msg}), 409

        usuario = db.autenticar_local(username, senha)
        return jsonify({
            "status": "sucesso",
            "name": usuario["name"],
            "role": usuario["role"],
            "isSuperAdmin": usuario["isSuperAdmin"],
            "token": gerar_token_sessao(usuario),
        })
    except Exception:
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

    Limitação conhecida: o token é assinado e sem estado, então trocar a
    senha NÃO derruba sessões já abertas — elas seguem válidas até
    expirarem (12h). Derrubar exigiria manter estado de sessão no servidor.
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
    if len(nova) < 4:
        return jsonify({"erro": "A nova senha precisa ter pelo menos 4 caracteres."}), 400
    if nova == atual:
        return jsonify({"erro": "A nova senha é igual à atual."}), 400

    uid = sessao.get("uid") or ""
    if not db.autenticar_local(uid, atual):
        return jsonify({"erro": "Senha atual incorreta."}), 403

    ok, msg = db.redefinir_senha_local(uid, nova)
    if not ok:
        return jsonify({"erro": msg}), 400

    return jsonify({"status": "sucesso"})


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
    # Diretoria ou TI); esse parâmetro é só uma PREFERÊNCIA de visualização,
    # nunca uma promoção: o papel real continua vindo do token assinado.
    modo_visualizacao = request.args.get('view_mode', role_real).strip().upper()

    if super_admin and modo_visualizacao in db.PAPEIS_VALIDOS:
        role_em_uso = modo_visualizacao
    else:
        role_em_uso = role_real

    # TI e Diretoria enxergam a fila inteira (todos os remetentes); o
    # coordenador só vê os próprios pedidos. Quem pode EDITAR continua
    # sendo só o TI — isso é decidido em outras rotas, não aqui.
    ve_tudo = role_em_uso in db.PAPEIS_VISAO_GLOBAL

    conn = db.get_connection()
    cursor = conn.cursor()

    # O escopo é decidido aqui, no servidor, com base no token — o cliente
    # não tem como ampliar a própria visão.
    colunas = ("id, professor_nome, materia, turma, arquivo_nome, copias, "
               "paginas, status, criado_em, impresso_em")
    if ve_tudo:
        cursor.execute(f"SELECT {colunas} FROM pedidos ORDER BY id DESC")
        linhas_banco = cursor.fetchall()
    else:
        cursor.execute(f"SELECT {colunas} FROM pedidos WHERE professor_nome=? ORDER BY id DESC", (user_name,))
        linhas_banco = cursor.fetchall()

    conn.close()

    pendentes = sum(1 for l in linhas_banco if l["status"] == "Pendente")
    imprimindo = sum(1 for l in linhas_banco if l["status"] == "Imprimindo")
    concluidos = sum(1 for l in linhas_banco if l["status"] == "Concluído")

    pedidos_lista = []
    contador_pendentes = 0

    for linha in linhas_banco:
        status_job = linha["status"]
        posicao_fila = "-"
        if status_job == 'Pendente':
            contador_pendentes += 1
            posicao_fila = f"{contador_pendentes}º"

        pedidos_lista.append({
            "id": linha["id"],
            "remetente": linha["professor_nome"],
            "materia_turma": f"{linha['materia']} — {linha['turma']}",
            "arquivo": linha["arquivo_nome"],
            "copias": linha["copias"],
            "paginas": linha["paginas"],
            "posicao": posicao_fila,
            "status": status_job,
            "criado_em": linha["criado_em"],
            "impresso_em": linha["impresso_em"],
        })

    return jsonify({
        "estatisticas": {"pendentes": pendentes, "imprimindo": imprimindo, "concluidos": concluidos},
        "pedidos": pedidos_lista
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
    else:
        # Formulário do coordenador: matéria + turma.
        materia = request.form.get('materia', 'Geral')
        turma = request.form.get('turma')
        if not turma:
            return jsonify({"erro": "Campos obrigatórios em falta"}), 400

    try:
        copias = int(request.form.get('copias', 1))
    except (TypeError, ValueError):
        return jsonify({"erro": "Número de cópias inválido."}), 400

    if copias < 1:
        return jsonify({"erro": "Número de cópias inválido."}), 400

    if not arquivo:
        return jsonify({"erro": "Campos obrigatórios em falta"}), 400

    # Validação do arquivo NO SERVIDOR (o limite de tamanho já é garantido
    # por MAX_CONTENT_LENGTH). Aceitamos apenas PDF: conferimos a extensão,
    # o mimetype declarado e os primeiros bytes do conteúdo (assinatura
    # "%PDF"), porque nenhum desses sinais isolado é confiável.
    nome_original = secure_filename(arquivo.filename)
    conteudo_pdf = arquivo.read()

    eh_pdf = (
        nome_original.lower().endswith(".pdf")
        and arquivo.mimetype == "application/pdf"
        and conteudo_pdf[:5] == b"%PDF-"
    )
    if not eh_pdf:
        return jsonify({"erro": "Apenas arquivos PDF válidos são aceitos."}), 400

    # COTA mensal (se habilitada): conta páginas × cópias deste arquivo e
    # confere se, somado ao que o usuário já gerou no mês, ainda cabe no
    # limite. Bloqueia ANTES de gravar, então nada entra na fila à toa.
    if LIMITE_MENSAL_IMPRESSOES > 0 and user_uid:
        paginas_estimadas = db.contar_paginas_pdf(conteudo_pdf) or 1
        impressoes_deste = paginas_estimadas * copias
        ja_usadas = db.consumo_mensal_impressoes(user_uid, datetime.now(FUSO_HORARIO).strftime("%Y-%m"))
        if ja_usadas + impressoes_deste > LIMITE_MENSAL_IMPRESSOES:
            restante = max(0, LIMITE_MENSAL_IMPRESSOES - ja_usadas)
            return jsonify({"erro": (
                f"Cota mensal de {LIMITE_MENSAL_IMPRESSOES} impressões excedida. "
                f"Este envio precisa de {impressoes_deste} e você tem {restante} disponível(is) "
                f"neste mês. Fale com o Departamento de T.I."
            )}), 403

    # O PDF vai direto para o banco (como BLOB), não para um caminho em
    # disco — no Discloud não há garantia de que um arquivo salvo em
    # disco sobreviva a um redeploy ou reinício do container. A criação do
    # pedido já carimba o horário, conta as páginas, calcula o hash e
    # registra o evento na trilha de auditoria (ver banco_dados).
    pedido_id, paginas, _hash = db.criar_pedido(
        user_name, user_uid, user_metodo, materia, turma, copias, cor,
        frente_verso, acabamento, nome_original, conteudo_pdf
    )

    # Note que NÃO chamamos mais a impressão por aqui — quem imprime agora
    # é o agente local, consultando as rotas abaixo. Devolvemos o protocolo
    # (o ID do pedido) e os dados que servem de comprovante ao professor.
    return jsonify({
        "status": "sucesso",
        "mensagem": mensagem_para_envio(),
        "protocolo": f"IMP-{pedido_id:04d}",
        "pedido_id": pedido_id,
        "paginas": paginas,
    })


# -------------------------------------------------------------------------
# ROTAS DO AGENTE DE IMPRESSÃO (rodando no computador do colégio)
# -------------------------------------------------------------------------
@app.route('/api/agente/pendentes', methods=['GET'])
def agente_pendentes():
    if not verificar_chave_agente():
        return jsonify({"erro": "Não autorizado"}), 401

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, professor_nome, materia, turma, copias, cor, frente_verso, acabamento
        FROM pedidos WHERE status = 'Pendente' ORDER BY id ASC
    ''')
    pedidos = [dict(linha) for linha in cursor.fetchall()]
    conn.close()

    return jsonify({"pedidos": pedidos})


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

    dados = request.json or {}
    novo_status = dados.get("status")

    if novo_status not in ("Imprimindo", "Concluído", "Erro"):
        return jsonify({"erro": "Status inválido"}), 400

    # Carimba o horário e registra na auditoria que foi o AGENTE quem mudou
    # o status (ator="agente"). Se o status virar 'Concluído', grava também
    # o impresso_em.
    encontrado = db.atualizar_status(pedido_id, novo_status, ator="agente")
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
    Edição/gestão continua exclusiva do TI."""
    role = sessao.get("role")
    if role == db.ROLE_TI:
        return True
    if tipo == "custos" and role == db.ROLE_DIRETOR_ADM:
        return True
    if tipo == "materias" and role == db.ROLE_DIRETORA_PED:
        return True
    return False


def _csv_resposta(cabecalho, linhas, nome_base, data_inicio, data_fim):
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecalho)
    for linha in linhas:
        escritor.writerow(linha)
    periodo = f"{data_inicio or 'inicio'}_a_{data_fim or 'hoje'}"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nome_base}_{periodo}.csv"'}
    )


@app.route('/api/relatorio', methods=['GET'])
def api_relatorio():
    """Relatórios de prestação de contas. O parâmetro 'tipo' escolhe qual:
      - 'consumo'  (padrão): por professor — TI.
      - 'custos'           : P&B × colorida — TI e Diretor Administrativo.
      - 'materias'         : documentos por matéria — TI e Diretora Pedagógica.
    Aceita data_inicio/data_fim ('YYYY-MM-DD') e formato=json|csv."""
    sessao = usuario_autenticado()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    tipo = request.args.get("tipo", "consumo").strip().lower()
    if not _pode_ver_relatorio(sessao, tipo):
        return jsonify({"erro": "Não autorizado"}), 401

    data_inicio = request.args.get("data_inicio", "").strip() or None
    data_fim = request.args.get("data_fim", "").strip() or None
    formato = request.args.get("formato", "json").strip().lower()
    periodo = {"inicio": data_inicio, "fim": data_fim}

    if tipo == "custos":
        dados = db.relatorio_custos(data_inicio, data_fim)
        if formato == "csv":
            linhas = [[p["professor_nome"], p["copias_pb"], p["copias_cor"],
                       p["impressoes_pb"], p["impressoes_cor"],
                       p["impressoes_pb"] + p["impressoes_cor"]] for p in dados["por_professor"]]
            return _csv_resposta(
                ["Professor", "Cópias P&B", "Cópias Colorida",
                 "Impressões P&B", "Impressões Colorida", "Impressões Total"],
                linhas, "relatorio_custos", data_inicio, data_fim)
        return jsonify({"periodo": periodo, **dados})

    if tipo == "materias":
        documentos = db.relatorio_por_materia(data_inicio, data_fim)
        if formato == "csv":
            linhas = [[d["materia"], d["professor_nome"], d["arquivo_nome"],
                       d["copias"], d["paginas"], d["criado_em"], d["status"]] for d in documentos]
            return _csv_resposta(
                ["Matéria", "Docente", "Arquivo", "Cópias", "Páginas", "Enviado em", "Status"],
                linhas, "relatorio_materias", data_inicio, data_fim)
        return jsonify({
            "periodo": periodo,
            "documentos": documentos,
            "totais": {
                "documentos": len(documentos),
                "impressoes": sum((d["paginas"] or 0) * d["copias"] for d in documentos),
            },
        })

    # tipo == "consumo" (padrão)
    linhas = db.relatorio_consumo(data_inicio, data_fim)
    if formato == "csv":
        return _csv_resposta(
            ["Professor", "Identificador", "Pedidos",
             "Total de cópias", "Total de páginas", "Total de impressões"],
            [[l["professor_nome"], l["usuario_uid"], l["pedidos"], l["total_copias"],
              l["total_paginas"], l["total_impressoes"]] for l in linhas],
            "relatorio_consumo", data_inicio, data_fim)
    return jsonify({
        "periodo": periodo,
        "linhas": linhas,
        "totais": {
            "impressoes": sum(l["total_impressoes"] for l in linhas),
            "copias": sum(l["total_copias"] for l in linhas),
            "pedidos": sum(l["pedidos"] for l in linhas),
        },
    })


@app.route('/api/relatorio/documento/<int:pedido_id>', methods=['GET'])
def api_relatorio_documento(pedido_id):
    """Abre o PDF de um pedido para conferência. Restrito ao TI e à
    Diretora Pedagógica (que precisa ver o que os docentes enviam)."""
    sessao = usuario_autenticado()
    if not sessao or sessao.get("role") not in (db.ROLE_TI, db.ROLE_DIRETORA_PED):
        return jsonify({"erro": "Não autorizado"}), 401

    arquivo = db.obter_arquivo_pedido(pedido_id)
    if arquivo and arquivo["purgado"]:
        return jsonify({"erro": "Arquivo expirado pela política de retenção"}), 410
    if not arquivo or not arquivo["conteudo"]:
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
    if len(senha) < 4:
        return jsonify({"erro": "A senha precisa ter pelo menos 4 caracteres."}), 400

    ok, msg = db.criar_usuario_local(
        dados.get('username', ''), senha, dados.get('name', ''),
        role=role, super_admin=0
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


@app.route('/api/admin/usuarios/<username>/senha', methods=['POST'])
def admin_resetar_senha(username):
    sessao = sessao_ti()
    if not sessao:
        return jsonify({"erro": "Não autorizado"}), 401

    nova = (request.json or {}).get('password', '')
    if len(nova) < 4:
        return jsonify({"erro": "A senha precisa ter pelo menos 4 caracteres."}), 400

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
    # host="0.0.0.0" faz o Flask escutar em todas as placas de rede —
    # necessário para os professores acessarem pelo IP da máquina servidora.
    app.run(host="0.0.0.0", debug=modo_debug, use_reloader=False, port=8080)
