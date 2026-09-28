"""
Camada de acesso ao banco de dados do Sistema de Impressão do Instituto Acalanto.

Este módulo é o ÚNICO lugar do projeto que conhece usuários, senhas e
privilégios de administrador. O app.py NUNCA deve declarar credenciais ou
papéis (roles) diretamente — apenas chamar as funções daqui.

O arquivo .db físico é criado DENTRO desta pasta (banco_dados/), separado
do resto do código. Isso facilita:
  1) Restringir o acesso ao arquivo (permissões de pasta) sem afetar o app.
  2) Excluir a pasta inteira do controle de versão (ver .gitignore ao lado).
  3) Trocar a forma de autenticação no futuro sem tocar nas rotas do Flask.

Além de usuários e pedidos, este módulo mantém uma TRILHA DE AUDITORIA
(tabela `eventos`): cada criação de pedido e cada mudança de status grava
um registro com carimbo de tempo e quem fez. É essa trilha que serve de
"garantia" para o Departamento — prova de quem pediu o quê, quando, e o
que aconteceu com cada pedido.
"""

import os
import hashlib
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from werkzeug.security import generate_password_hash, check_password_hash

# -------------------------------------------------------------------------
# LOCALIZAÇÃO DO BANCO DE DADOS
# -------------------------------------------------------------------------
_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_PASTA_ATUAL, "acalanto_print.db")

# Papéis (roles) reconhecidos pelo sistema.
#   TI            -> Departamento: controle total.
#   DIRETOR_ADM   -\
#   DIRETORA_PED  -/  Diretoria: vê a fila de todos (leitura), sem editar.
#   COORDENADOR   -> Professor: vê e envia apenas o que é seu.
#   COORDENACAO   -> Coordenadora de segmento: vê e envia como o COORDENADOR,
#                     mais enxerga a fila/relatório dos professores do MESMO
#                     segmento (ver SEGMENTO_* abaixo). ARMADILHA DE NOME: é
#                     um papel diferente do COORDENADOR, apesar do nome
#                     parecido — o COORDENADOR já gravado no banco é o
#                     professor comum, e esse valor não muda.
ROLE_TI = "TI"
ROLE_DIRETOR_ADM = "DIRETOR_ADM"
ROLE_DIRETORA_PED = "DIRETORA_PED"
ROLE_COORDENADOR = "COORDENADOR"
ROLE_COORDENACAO = "COORDENACAO"

# Conjuntos auxiliares para as regras de acesso ficarem num lugar só.
# Não existe um conjunto "visão global": quem enxerga o quê é decidido em
# tempo de execução por escopo_de_visao(), em app.py, porque a visão da
# COORDENACAO depende dos segmentos da conta.
PAPEIS_DIRETORIA = {ROLE_DIRETOR_ADM, ROLE_DIRETORA_PED}
# Papéis que podem ser atribuídos a uma conta.
PAPEIS_VALIDOS = {ROLE_TI, ROLE_COORDENADOR, ROLE_COORDENACAO} | PAPEIS_DIRETORIA

# -------------------------------------------------------------------------
# SEGMENTOS (coordenações da escola)
# -------------------------------------------------------------------------
# Cada pedido é CARIMBADO com o segmento no momento do envio (não derivado
# do professor na hora da consulta): professor_nome é texto livre sem FK, e
# quem dá aula em mais de um segmento (inglês, ed. física...) não tem um
# segmento fixo que sirva pra todo pedido que ele manda. O relatório também
# precisa refletir o que era verdade na época do envio, não a lotação atual
# da pessoa.
#
# GERAL não é "mais um segmento de turma": é ao mesmo tempo (a) o escopo de
# quem enxerga a escola inteira (COORDENACAO + segmento GERAL) e (b) o
# bucket dos pedidos do Ensino Médio, porque hoje é a mesma pessoa que
# acumula os dois papéis — não existe uma coordenadora dedicada só ao
# Médio. Se um dia existir, basta cadastrar essa conta com um segmento
# próprio; nada aqui precisa mudar.
SEGMENTO_INFANTIL = "INFANTIL"
SEGMENTO_FUND1 = "FUND1"
SEGMENTO_FUND2 = "FUND2"
SEGMENTO_GERAL = "GERAL"

SEGMENTOS_VALIDOS = (SEGMENTO_INFANTIL, SEGMENTO_FUND1, SEGMENTO_FUND2, SEGMENTO_GERAL)

# O código gravado no banco é ASCII e estável; o rótulo acentuado é só
# apresentação — nunca grave o rótulo, apenas o código.
ROTULOS_SEGMENTO = {
    SEGMENTO_INFANTIL: "Educação Infantil",
    SEGMENTO_FUND1: "Fundamental I",
    SEGMENTO_FUND2: "Fundamental II",
    SEGMENTO_GERAL: "Geral / Ensino Médio",
}


# Uma CONTA pode participar de mais de um segmento (coordenador de área que
# dá aula no Fund. I e no Fund. II, por exemplo). A coluna `segmento` de
# usuarios_locais guarda os códigos separados por vírgula ("FUND1,FUND2") —
# um valor antigo de código único ("FUND1") continua sendo lido normalmente,
# então não há migração de dados. O segmento de um PEDIDO segue sendo UM só:
# cada envio é de uma turma, e é o carimbo único que decide qual coordenação
# enxerga aquele pedido.
def normalizar_segmentos(bruto):
    """Converte o que vier (None, "FUND1", "FUND1,FUND2" ou lista) na lista
    canônica de códigos: sem repetição, na ordem de SEGMENTOS_VALIDOS.
    Código desconhecido é descartado silenciosamente — mesmo espírito do
    'role' desconhecido em criar_usuario_local. Devolve [] se nada sobrar."""
    if bruto is None:
        itens = []
    elif isinstance(bruto, str):
        itens = bruto.split(",")
    else:
        itens = list(bruto)
    codigos = {str(item).strip().upper() for item in itens if str(item).strip()}
    return [s for s in SEGMENTOS_VALIDOS if s in codigos]


def segmentos_para_texto(segmentos):
    """Lista de códigos -> texto que vai para a coluna ("FUND1,FUND2"),
    ou None quando a lista fica vazia (conta sem segmento definido)."""
    lista = normalizar_segmentos(segmentos)
    return ",".join(lista) if lista else None


def rotulo_segmentos(segmentos):
    """Rótulo humano da lista ("Fundamental I e Fundamental II"), ou None
    se a lista ficar vazia. Aceita o mesmo que normalizar_segmentos."""
    rotulos = [ROTULOS_SEGMENTO[s] for s in normalizar_segmentos(segmentos)]
    if not rotulos:
        return None
    if len(rotulos) == 1:
        return rotulos[0]
    return " e ".join([", ".join(rotulos[:-1]), rotulos[-1]])

# Área institucional de cada cargo da Diretoria. É o servidor (e não o
# navegador) que decide isso, a partir do cargo — assim ninguém "escolhe"
# a própria área ao enviar uma impressão.
_AREA_POR_CARGO = {
    ROLE_DIRETOR_ADM: "Administrativa",
    ROLE_DIRETORA_PED: "Pedagógica",
}

# Os mesmos valores, como marca reservada: um envio com turma igual a uma
# área institucional só pode ter vindo da Diretoria — a rota de envio recusa
# texto livre que colida com isso (ver api_enviar em app.py).
AREAS_INSTITUCIONAIS = tuple(_AREA_POR_CARGO.values())


def area_da_diretoria(role):
    """Devolve a área ('Administrativa'/'Pedagógica') do cargo de Diretoria,
    ou '' se o cargo não for de diretor."""
    return _AREA_POR_CARGO.get(role, "")


# -------------------------------------------------------------------------
# TURMAS E MATÉRIAS
# -------------------------------------------------------------------------
# Listas fechadas: no formulário do coordenador esses dois campos são caixas
# de seleção, não mais texto digitado. O texto livre deixava o mesmo ano
# letivo entrar de várias formas ("6 Ano", "6º Ano", "1º Ano - Ensino Médio",
# "2º Ano E.M") e o relatório por matéria agrupa por igualdade exata — cada
# variação virava uma linha separada.
#
# A lista vive aqui e é espelhada no front em `types.ts`. O servidor revalida
# o que chega: a caixa de seleção limita a tela, não a requisição.
TURMAS_VALIDAS = (
    # Educação Infantil (não existe "Jardim 3" no colégio)
    "Maternal 1", "Maternal 2", "Jardim 1", "Jardim 2",
    # Ensino Fundamental I
    "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano",
    # Ensino Fundamental II
    "6º Ano", "7º Ano", "8º Ano", "9º Ano",
    # Ensino Médio
    "1º EM", "2º EM", "3º EM",
)

# Em ordem alfabética — a mesma ordem em que aparecem na tela.
MATERIAS_VALIDAS = (
    "Biologia", "Ciências", "Filosofia", "Física", "Geografia", "História",
    "Inglês", "Matemática", "Português", "Química", "Sociologia",
)

# Papel A3 NÃO passa pelo sistema (decisão da gestão em ago/2026): A3 é
# impressão especial, tratada direto com o T.I. O sistema imprime tudo no
# padrão da fila (A4). Se um dia voltar, o token do SumatraPDF é
# "paper=A3" — conferido no binário 3.6.1.

# A opção "Outro" abre um campo de texto para o que não é matéria regular
# (capa de avaliação, simulado, recuperação). Tem tamanho máximo e passa
# por limpeza antes do banco.
MATERIA_OUTRO_MAX = 60

# Mesmo arranjo para a turma: o professor às vezes imprime algo que não é
# de turma nenhuma (material de uso próprio, reunião de pais, formação).
# A opção "Outro" da tela abre um campo de texto com a mesma limpeza.
TURMA_OUTRO_MAX = 60


def _normalizar_texto_livre(bruto, maximo):
    """Texto do campo "Outro" pronto para gravar: uma linha só, sem
    caracteres de controle, cortado no tamanho máximo."""
    texto = "".join(c if c.isprintable() else " " for c in (bruto or ""))
    texto = " ".join(texto.split())
    return texto[:maximo].strip()


def normalizar_materia(bruto):
    """Devolve a matéria pronta para gravar, ou '' se não sobrar nada.

    Uma das matérias listadas passa direto. Qualquer outra coisa é tratada
    como texto do campo "Outro": vira uma linha só, sem caracteres de
    controle, cortada em MATERIA_OUTRO_MAX.
    """
    texto = (bruto or "").strip()
    if texto in MATERIAS_VALIDAS:
        return texto
    return _normalizar_texto_livre(texto, MATERIA_OUTRO_MAX)


def normalizar_turma(bruto):
    """Devolve a turma pronta para gravar, ou '' se não sobrar nada.

    Uma das TURMAS_VALIDAS passa direto. Qualquer outra coisa é o texto da
    opção "Outro" (uso próprio, reunião de pais...) — mesma limpeza da
    matéria. A lista fechada continua sendo o caminho normal; o texto livre
    existe porque nem toda impressão pertence a uma turma.
    """
    texto = (bruto or "").strip()
    if texto in TURMAS_VALIDAS:
        return texto
    return _normalizar_texto_livre(texto, TURMA_OUTRO_MAX)


# Todos os registros de tempo usam o fuso do colégio, gravados como texto
# ISO 8601 (ex.: "2026-06-24T10:30:00-03:00"). Texto ISO ordena na mesma
# ordem do tempo e é fácil de filtrar por mês ("2026-06").
_FUSO = ZoneInfo("America/Sao_Paulo")


def agora_iso():
    return datetime.now(_FUSO).isoformat(timespec="seconds")


# -------------------------------------------------------------------------
# CONEXÃO
# -------------------------------------------------------------------------
def get_connection():
    """Conexão com o banco, com espera por lock e WAL.

    `timeout=15`: sem ele, o padrão do sqlite3 é 5s e qualquer escrita
    concorrente (o agente confirmando um status enquanto um professor
    envia um PDF de 50 MB) vira "database is locked" — que, no caminho da
    confirmação, significava pedido preso e reimpressão. Esperar é melhor
    que falhar.

    WAL deixa leitura e escrita conviverem: a fila de um professor não
    espera mais a gravação de outro terminar. É uma propriedade do arquivo,
    então basta pedir uma vez, mas repetir é inofensivo."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
    except sqlite3.Error:
        # Banco em rede ou sistema de arquivos que não aceita WAL: seguimos
        # no modo padrão em vez de derrubar a conexão.
        pass
    return conn


# -------------------------------------------------------------------------
# CRIAÇÃO DAS TABELAS, MIGRAÇÃO E SEED INICIAL
# -------------------------------------------------------------------------
def init_db():
    os.makedirs(_PASTA_ATUAL, exist_ok=True)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_nome TEXT NOT NULL,
            usuario_uid TEXT,
            usuario_metodo TEXT,
            materia TEXT NOT NULL,
            turma TEXT NOT NULL,
            copias INTEGER NOT NULL,
            cor TEXT NOT NULL,
            frente_verso TEXT NOT NULL,
            acabamento TEXT NOT NULL,
            arquivo_nome TEXT NOT NULL,
            arquivo_conteudo BLOB,
            arquivo_hash TEXT,
            arquivo_purgado INTEGER NOT NULL DEFAULT 0,
            paginas INTEGER,
            status TEXT DEFAULT 'Pendente',
            criado_em TEXT,
            atualizado_em TEXT,
            impresso_em TEXT
        )
    ''')

    # TRILHA DE AUDITORIA: nunca se atualiza nem se apaga — só se acrescenta.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            evento TEXT NOT NULL,
            ator TEXT NOT NULL,
            detalhe TEXT,
            criado_em TEXT NOT NULL
        )
    ''')

    # Contas Google Workspace (login com conta institucional)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios_workspace (
            email TEXT PRIMARY KEY NOT NULL,
            nome_completo TEXT NOT NULL,
            role TEXT NOT NULL,
            super_admin INTEGER NOT NULL DEFAULT 0
        )
    ''')

    # Contas locais (usuário/senha do servidor). É AQUI, e só aqui, que
    # moram as credenciais e o privilégio de administrador (super_admin).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios_locais (
            username TEXT PRIMARY KEY NOT NULL,
            senha_hash TEXT NOT NULL,
            nome_completo TEXT NOT NULL,
            role TEXT NOT NULL,
            super_admin INTEGER NOT NULL DEFAULT 0
        )
    ''')

    # Estado do sistema, em pares chave/valor. Hoje guarda um item só: o
    # último sinal de vida do agente de impressão (ver registrar_heartbeat).
    # Uma tabela genérica evita criar uma tabela nova para cada dado
    # solitário desse tipo.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS estado_sistema (
            chave TEXT PRIMARY KEY NOT NULL,
            valor TEXT,
            atualizado_em TEXT
        )
    ''')

    conn.commit()
    _migrar_pedidos(cursor, conn)
    _migrar_usuarios_locais(cursor, conn)
    _criar_indices(cursor, conn)
    _seed_usuarios_locais(cursor, conn)
    _seed_usuarios_workspace(cursor, conn)
    conn.close()


def _criar_indices(cursor, conn):
    """Índices das consultas que rodam sempre.

    A mais frequente de todas é a do agente: `WHERE status='Pendente'
    ORDER BY id`, a cada 15 segundos — algo como 5.760 vezes por dia. Sem
    índice, cada uma dessas é uma varredura da tabela inteira, e essa
    tabela carrega os PDFs como BLOB: a varredura atravessa páginas de
    dados que não interessam em nada à consulta.

    Os outros três cobrem os recortes de /api/fila (por conta e por
    segmento) e o filtro de período dos relatórios. CREATE INDEX IF NOT
    EXISTS é idempotente — roda a cada inicialização sem custo.
    """
    for indice in (
        "CREATE INDEX IF NOT EXISTS idx_pedidos_status ON pedidos(status, id)",
        "CREATE INDEX IF NOT EXISTS idx_pedidos_uid ON pedidos(usuario_uid, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pedidos_segmento ON pedidos(segmento, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pedidos_criado ON pedidos(criado_em)",
        "CREATE INDEX IF NOT EXISTS idx_eventos_pedido ON eventos(pedido_id, id)",
    ):
        cursor.execute(indice)
    conn.commit()


def _migrar_pedidos(cursor, conn):
    """Adiciona as colunas novas a um banco que já existia antes desta
    versão. ALTER TABLE ADD COLUMN é idempotente aqui porque conferimos
    antes o que já está na tabela — rodar duas vezes não dá erro."""
    cursor.execute("PRAGMA table_info(pedidos)")
    colunas_existentes = {linha["name"] for linha in cursor.fetchall()}

    colunas_novas = {
        "usuario_uid": "TEXT",
        "usuario_metodo": "TEXT",
        "arquivo_hash": "TEXT",
        "arquivo_purgado": "INTEGER NOT NULL DEFAULT 0",
        "paginas": "INTEGER",
        "criado_em": "TEXT",
        "atualizado_em": "TEXT",
        "impresso_em": "TEXT",
        # Segmento carimbado no envio (ver comentário em SEGMENTOS_VALIDOS).
        # Pedidos antigos ficam NULL = "não definido": visíveis ao T.I., à
        # Coordenação Geral e à Diretoria Pedagógica, mas não às
        # coordenadoras de segmento — nunca inferimos o segmento a partir da
        # turma numa migração automática, é palpite silencioso sobre dado real.
        "segmento": "TEXT",
        # Quando o agente RESERVOU o pedido (status virou 'Imprimindo').
        # É o relógio que identifica pedido preso — ver
        # sinalizar_pedidos_presos().
        "reservado_em": "TEXT",
        # Identificador da reserva (um por tentativa de impressão). Serve
        # para a reserva ser IDEMPOTENTE: se o agente reservou e a resposta
        # se perdeu na rede, ele reapresenta o mesmo identificador e recebe
        # "é sua" em vez de 409 — sem isso o pedido congelava em
        # 'Imprimindo' sem nada ser impresso.
        "reservado_por": "TEXT",
        # FOLHAS DE PAPEL do pedido, calculadas no envio (ver
        # opcoes_impressao.folhas_do_pedido). Gravada, e não calculada no
        # relatório, por três razões: o relatório vira SUM(); se a regra
        # mudar, o pedido antigo preserva o número que era verdade na época;
        # e é o mesmo valor que o teto por envio já precisa calcular.
        "folhas": "INTEGER",
        # Motivo do último erro, em português, vindo do agente ("a
        # impressora estava sem papel"). Sem isso o professor vê "Erro" e
        # não sabe se reenvia, espera ou liga para alguém.
        "erro_motivo": "TEXT",
    }

    for nome, definicao in colunas_novas.items():
        if nome not in colunas_existentes:
            cursor.execute(f"ALTER TABLE pedidos ADD COLUMN {nome} {definicao}")

    # Pedido que já estava em 'Imprimindo' antes de reservado_em existir
    # recebe o carimbo do último toque (atualizado_em/criado_em). Sem isso,
    # reservado_em NULL escaparia da conferência de idade e o pedido seria
    # tratado como "preso agora" na primeira inicialização depois do
    # deploy — justamente os pedidos cujo papel provavelmente já saiu.
    cursor.execute('''
        UPDATE pedidos
           SET reservado_em = COALESCE(atualizado_em, criado_em)
         WHERE status = 'Imprimindo' AND reservado_em IS NULL
    ''')

    # Preenche 'folhas' no histórico: frente_verso e paginas já estavam
    # gravados, então o número é recuperável para todo pedido antigo.
    # (paginas + 1) / 2 na divisão inteira do SQLite dá o teto (7 -> 4).
    # Registro com frente_verso vazio cai em simplex, o que SUPERESTIMA o
    # papel — erro para o lado seguro do orçamento. O LIKE cobre as duas
    # formas que já apareceram no banco ('FrenteVerso' e 'Frente e Verso').
    # `AND paginas IS NOT NULL`: sem páginas contadas não há folhas a
    # deduzir, e gravar 0 seria pior que deixar NULL — o pedido passaria a
    # valer ZERO folha nos relatórios (e a migração, que roda a cada
    # inicialização, faria isso com todo pedido novo cujo PDF o pypdf não
    # conseguiu ler). Com NULL, o fallback COALESCE dos relatórios entra e
    # conta páginas × cópias.
    cursor.execute('''
        UPDATE pedidos
           SET folhas = CASE
                 WHEN LOWER(COALESCE(frente_verso, '')) LIKE '%verso%'
                   THEN ((paginas + 1) / 2) * copias
                 ELSE paginas * copias
               END
         WHERE folhas IS NULL AND paginas IS NOT NULL
    ''')

    conn.commit()


def _migrar_usuarios_locais(cursor, conn):
    """Mesmo padrão de _migrar_pedidos: acrescenta colunas novas a um banco
    que já existia antes desta versão, sem quebrar ao rodar de novo."""
    cursor.execute("PRAGMA table_info(usuarios_locais)")
    colunas_existentes = {linha["name"] for linha in cursor.fetchall()}

    colunas_novas = {
        "segmento": "TEXT",
        # VERSÃO DO TOKEN. Vai dentro do token de sessão e é conferida a
        # cada requisição: trocar ou resetar a senha incrementa este número
        # e, com isso, DERRUBA as sessões já abertas daquela conta. Sem
        # isso, uma senha comprometida continuava valendo por até 12h,
        # porque o token é assinado e sem estado.
        "token_version": "INTEGER NOT NULL DEFAULT 0",
    }

    for nome, definicao in colunas_novas.items():
        if nome not in colunas_existentes:
            cursor.execute(f"ALTER TABLE usuarios_locais ADD COLUMN {nome} {definicao}")

    conn.commit()


def _seed_usuarios_locais(cursor, conn):
    cursor.execute("SELECT COUNT(*) FROM usuarios_locais")
    if cursor.fetchone()[0] > 0:
        return

    # ------------------------------------------------------------------
    # ÚNICO lugar do projeto onde contas locais e privilégios existem.
    # super_admin = 1  ->  pode alternar livremente entre os modos
    #                      Professor e Departamento de T.I. na interface.
    # ------------------------------------------------------------------
    # A senha inicial do admin vem do .env (ADMIN_SENHA_INICIAL). Se não
    # estiver definida, uma senha aleatória é gerada e mostrada no terminal
    # uma única vez. Troque-a no primeiro acesso.
    senha_admin = os.environ.get("ADMIN_SENHA_INICIAL")
    if not senha_admin:
        import secrets
        senha_admin = secrets.token_urlsafe(12)
        print(f"[banco_dados] Senha inicial gerada para 'admin': {senha_admin}")

    contas_iniciais = [
        # username,  senha,        nome_completo,    role,     super_admin
        ("admin",    senha_admin,  "Administrador",  ROLE_TI,  1),
    ]

    for username, senha, nome, role, super_admin in contas_iniciais:
        cursor.execute('''
            INSERT INTO usuarios_locais (username, senha_hash, nome_completo, role, super_admin)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, generate_password_hash(senha), nome, role, super_admin))

    conn.commit()


def _seed_usuarios_workspace(cursor, conn):
    cursor.execute("SELECT COUNT(*) FROM usuarios_workspace")
    if cursor.fetchone()[0] > 0:
        return

    # Exemplos fictícios. Cadastre os e-mails reais pelo painel de usuários.
    usuarios_seeding = [
        ("ti@exemplo.com", "Usuário T.I. (exemplo)", ROLE_TI, 0),
        ("coordenacao@exemplo.com", "Coordenação (exemplo)", ROLE_COORDENADOR, 0),
    ]
    cursor.executemany('''
        INSERT INTO usuarios_workspace (email, nome_completo, role, super_admin)
        VALUES (?, ?, ?, ?)
    ''', usuarios_seeding)
    conn.commit()


# -------------------------------------------------------------------------
# AUTENTICAÇÃO LOCAL
# -------------------------------------------------------------------------
def autenticar_local(username, senha):
    """Confere usuário/senha contra usuarios_locais.
    Retorna {name, role, isSuperAdmin, uid, metodo, segmento} ou None se
    inválido. O 'uid' (o próprio username) identifica a conta de forma
    única — o nome completo não serve porque pode se repetir entre contas.
    O 'segmento' vai para dentro do token de sessão: é dele que
    escopo_de_visao() (em app.py) decide o que uma COORDENACAO enxerga, sem
    precisar reconsultar o banco a cada requisição."""
    conn = get_connection()
    cursor = conn.cursor()
    username = username.lower()
    cursor.execute(
        "SELECT senha_hash, nome_completo, role, super_admin, segmento, token_version "
        "FROM usuarios_locais WHERE username = ?",
        (username,)
    )
    linha = cursor.fetchone()
    conn.close()

    if not linha or not check_password_hash(linha["senha_hash"], senha):
        return None

    segmentos = normalizar_segmentos(linha["segmento"])
    return {
        "name": linha["nome_completo"],
        "role": linha["role"],
        "isSuperAdmin": bool(linha["super_admin"]),
        "uid": username,
        "metodo": "local",
        # 'segmentos' é a forma nova (lista); 'segmento' continua existindo
        # para quem ainda lê o valor único — recebe o código quando a conta
        # tem exatamente um, e None quando tem vários (não existe "o"
        # segmento de quem participa de mais de um).
        "segmento": segmentos[0] if len(segmentos) == 1 else None,
        "segmentos": segmentos,
        "token_version": linha["token_version"] or 0,
    }


def obter_token_version(username):
    """Versão atual do token da conta, ou None se a conta não existe mais.

    É o que permite ao servidor recusar um token cuja senha já foi trocada:
    o número dentro do token tem que bater com o do banco. Conta apagada
    devolve None e a sessão cai — que é o comportamento certo."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT token_version FROM usuarios_locais WHERE username = ?",
        ((username or "").strip().lower(),)
    )
    linha = cursor.fetchone()
    conn.close()
    return None if linha is None else (linha["token_version"] or 0)


# -------------------------------------------------------------------------
# GESTÃO DE CONTAS LOCAIS (auto-cadastro + administração pelo TI)
# -------------------------------------------------------------------------
def criar_usuario_local(username, senha, nome_completo, role=ROLE_COORDENADOR, super_admin=0, segmento=None):
    """Cadastra uma conta local. O username é guardado em minúsculas (o
    login também compara em minúsculas). Retorna (True, None) em caso de
    sucesso ou (False, mensagem) se algo impedir — ex.: usuário já existe.
    'segmento' aceita um código, texto com vírgulas ("FUND1,FUND2") ou uma
    lista; código fora de SEGMENTOS_VALIDOS é silenciosamente ignorado —
    mesmo tratamento que já dávamos a um 'role' desconhecido."""
    username = (username or "").strip().lower()
    nome_completo = (nome_completo or "").strip()
    segmento = segmentos_para_texto(segmento)

    if not username or not senha or not nome_completo:
        return False, "Preencha nome, usuário e senha."
    if " " in username:
        return False, "O nome de usuário não pode conter espaços."
    if role not in PAPEIS_VALIDOS:
        role = ROLE_COORDENADOR

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM usuarios_locais WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return False, "Esse nome de usuário já existe."

    cursor.execute('''
        INSERT INTO usuarios_locais (username, senha_hash, nome_completo, role, super_admin, segmento)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (username, generate_password_hash(senha), nome_completo, role, 1 if super_admin else 0, segmento))
    conn.commit()
    conn.close()
    return True, None


def listar_usuarios_locais():
    """Lista as contas locais (sem o hash da senha) para o painel do TI."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, nome_completo, role, super_admin, segmento FROM usuarios_locais ORDER BY nome_completo"
    )
    usuarios = [{
        "username": linha["username"],
        "name": linha["nome_completo"],
        "role": linha["role"],
        "isSuperAdmin": bool(linha["super_admin"]),
        "segmento": linha["segmento"],
        "segmentos": normalizar_segmentos(linha["segmento"]),
    } for linha in cursor.fetchall()]
    conn.close()
    return usuarios


def obter_usuario_local(username):
    """Retorna os dados públicos de uma conta local, ou None se não existir."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, nome_completo, role, super_admin, segmento FROM usuarios_locais WHERE username = ?",
        ((username or "").strip().lower(),)
    )
    linha = cursor.fetchone()
    conn.close()
    if not linha:
        return None
    return {
        "username": linha["username"],
        "name": linha["nome_completo"],
        "role": linha["role"],
        "isSuperAdmin": bool(linha["super_admin"]),
        "segmento": linha["segmento"],
        "segmentos": normalizar_segmentos(linha["segmento"]),
    }


def atualizar_role_local(username, novo_role):
    """Define o cargo de uma conta (COORDENADOR, COORDENACAO, DIRETOR_ADM,
    DIRETORA_PED ou TI). Retorna (True, None) ou (False, mensagem)."""
    if novo_role not in PAPEIS_VALIDOS:
        return False, "Cargo inválido."
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE usuarios_locais SET role = ? WHERE username = ?",
        (novo_role, (username or "").strip().lower())
    )
    alteradas = cursor.rowcount
    conn.commit()
    conn.close()
    return (alteradas > 0), (None if alteradas else "Usuário não encontrado.")


def definir_segmento_usuario_local(username, segmento):
    """Define o(s) segmento(s) de uma conta local. Para um professor comum
    (COORDENADOR) é o que pré-preenche o formulário de envio; para uma
    COORDENACAO é o que define o escopo de visão (ver escopo_de_visao() em
    app.py). Aceita um código, texto com vírgulas ("FUND1,FUND2") ou lista;
    None/""/lista vazia limpa (conta volta a 'não definido'). Diferente do
    cadastro, aqui código desconhecido é ERRO, não descarte silencioso — é
    o T.I. definindo escopo de visão, e gravar menos do que ele pediu seria
    esconder o engano. Retorna (True, None) ou (False, mensagem)."""
    if segmento is None:
        itens = []
    elif isinstance(segmento, str):
        itens = [t.strip().upper() for t in segmento.split(",") if t.strip()]
    else:
        itens = [str(t).strip().upper() for t in segmento if str(t).strip()]
    if any(item not in SEGMENTOS_VALIDOS for item in itens):
        return False, "Segmento inválido."
    texto = segmentos_para_texto(itens)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE usuarios_locais SET segmento = ? WHERE username = ?",
        (texto, (username or "").strip().lower())
    )
    alteradas = cursor.rowcount
    conn.commit()
    conn.close()
    return (alteradas > 0), (None if alteradas else "Usuário não encontrado.")


def redefinir_senha_local(username, nova_senha):
    """Troca a senha de uma conta local (reset do TI ou troca pela própria
    pessoa) e INCREMENTA token_version, derrubando as sessões já abertas
    daquela conta.

    Isso é o que torna uma senha comprometida de fato revogável: sem o
    incremento, o token antigo continuaria válido até expirar (12h), mesmo
    depois da troca — que é exatamente o cenário de "alguém pegou a conta e
    eu troquei a senha correndo"."""
    if not nova_senha:
        return False, "Senha vazia."
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE usuarios_locais "
        "SET senha_hash = ?, token_version = COALESCE(token_version, 0) + 1 "
        "WHERE username = ?",
        (generate_password_hash(nova_senha), (username or "").strip().lower())
    )
    alteradas = cursor.rowcount
    conn.commit()
    conn.close()
    return (alteradas > 0), (None if alteradas else "Usuário não encontrado.")


def remover_usuario_local(username):
    """Apaga uma conta local. Retorna True se removeu algo."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM usuarios_locais WHERE username = ?",
        ((username or "").strip().lower(),)
    )
    removidas = cursor.rowcount
    conn.commit()
    conn.close()
    return removidas > 0


# -------------------------------------------------------------------------
# GOOGLE WORKSPACE
# -------------------------------------------------------------------------
def obter_ou_cadastrar_workspace(email, nome_sugerido):
    """Busca um usuário Google Workspace; se não existir, cadastra
    automaticamente como COORDENADOR (sem privilégio de admin). O 'uid' é
    o próprio e-mail institucional, que identifica a conta unicamente."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nome_completo, role, super_admin FROM usuarios_workspace WHERE email = ?",
        (email,)
    )
    linha = cursor.fetchone()

    if linha:
        resultado = {
            "name": linha["nome_completo"],
            "role": linha["role"],
            "isSuperAdmin": bool(linha["super_admin"]),
            "uid": email,
            "metodo": "google",
        }
        conn.close()
        return resultado

    cursor.execute('''
        INSERT INTO usuarios_workspace (email, nome_completo, role, super_admin)
        VALUES (?, ?, ?, 0)
    ''', (email, nome_sugerido, ROLE_COORDENADOR))
    conn.commit()
    conn.close()

    return {
        "name": nome_sugerido,
        "role": ROLE_COORDENADOR,
        "isSuperAdmin": False,
        "uid": email,
        "metodo": "google",
    }


# -------------------------------------------------------------------------
# TRILHA DE AUDITORIA
# -------------------------------------------------------------------------
def registrar_evento(cursor, pedido_id, evento, ator, detalhe=""):
    """Acrescenta uma linha à trilha de auditoria. Recebe um cursor já
    aberto para participar da MESMA transação do pedido — ou o pedido e o
    evento são gravados juntos, ou nenhum dos dois."""
    cursor.execute('''
        INSERT INTO eventos (pedido_id, evento, ator, detalhe, criado_em)
        VALUES (?, ?, ?, ?, ?)
    ''', (pedido_id, evento, ator, detalhe, agora_iso()))


def listar_eventos(pedido_id):
    """Histórico completo (auditoria) de um pedido, do mais antigo ao mais
    recente."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT evento, ator, detalhe, criado_em FROM eventos WHERE pedido_id = ? ORDER BY id ASC",
        (pedido_id,)
    )
    eventos = [dict(linha) for linha in cursor.fetchall()]
    conn.close()
    return eventos


# -------------------------------------------------------------------------
# PEDIDOS — CRIAÇÃO E MUDANÇA DE STATUS (com carimbo de tempo e auditoria)
# -------------------------------------------------------------------------
def contar_paginas_pdf(conteudo_pdf):
    """Conta as páginas do PDF. Devolve None se o arquivo não puder ser
    lido (PDF corrompido/protegido)."""
    return analisar_pdf(conteudo_pdf)["paginas"]


def analisar_pdf(conteudo_pdf):
    """Lê o PDF uma vez e devolve {paginas, cifrado, legivel}.

    Separar "não consegui ler" de "está protegido por senha" importa: um
    PDF cifrado é aceito pelo servidor, mas o SumatraPDF depois NÃO
    consegue imprimi-lo — e com -silent ele não reclama, então o pedido
    terminaria como "Concluído" sem papel nenhum sair. Quem chama recusa o
    envio na hora, com uma mensagem que diz o que fazer.

    Existe uma função só para isso porque a leitura do PDF (até 50 MB) é a
    parte cara do envio: ela deve acontecer UMA vez, e o resultado
    (páginas) segue para o teto de folhas e para o pedido, sem reabrir o
    arquivo.
    """
    resultado = {"paginas": None, "cifrado": False, "legivel": False}
    try:
        from io import BytesIO
        from pypdf import PdfReader
        leitor = PdfReader(BytesIO(conteudo_pdf))
        resultado["cifrado"] = bool(leitor.is_encrypted)
        if resultado["cifrado"]:
            # Num PDF cifrado, len(pages) pode até funcionar (cifra com
            # senha vazia), mas a impressão não é garantida — tratamos como
            # não utilizável e deixamos a decisão para o chamador.
            return resultado
        resultado["paginas"] = len(leitor.pages)
        resultado["legivel"] = True
    except Exception:
        pass
    return resultado


def criar_pedido(remetente, usuario_uid, usuario_metodo, materia, turma,
                 copias, cor, frente_verso, acabamento, arquivo_nome,
                 arquivo_conteudo, segmento=None, paginas=None, folhas=None):
    """Grava um novo pedido com carimbo de tempo, contagem de páginas e
    hash SHA-256 do arquivo, e registra o evento de criação na auditoria.
    Retorna (pedido_id, paginas, arquivo_hash).

    'segmento' é CARIMBADO aqui, na hora do envio — não é derivado depois a
    partir do professor (ver comentário em SEGMENTOS_VALIDOS). Quem decide
    o valor é o chamador (app.py); esta função só grava o que recebeu.

    'paginas' e 'folhas' também vêm do chamador, que precisa dos dois ANTES
    de gravar (para conferir o teto por envio). Passá-los evita fazer o
    pypdf percorrer o mesmo arquivo de 50 MB duas vezes por envio. Se
    'paginas' não vier, contamos aqui — mantém compatível quem chama do
    jeito antigo."""
    if paginas is None:
        paginas = contar_paginas_pdf(arquivo_conteudo)
    arquivo_hash = hashlib.sha256(arquivo_conteudo).hexdigest()
    agora = agora_iso()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pedidos (
            professor_nome, usuario_uid, usuario_metodo, materia, turma,
            copias, cor, frente_verso, acabamento, arquivo_nome,
            arquivo_conteudo, arquivo_hash, paginas, status,
            criado_em, atualizado_em, segmento, folhas
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?, ?, ?)
    ''', (remetente, usuario_uid, usuario_metodo, materia, turma, copias, cor,
          frente_verso, acabamento, arquivo_nome, arquivo_conteudo,
          arquivo_hash, paginas, agora, agora, segmento, folhas))

    pedido_id = cursor.lastrowid
    detalhe = (
        f"{copias} cópia(s); {paginas if paginas is not None else '?'} pág.; "
        f"{folhas if folhas is not None else '?'} folha(s); "
        f"{cor}; {frente_verso}; {acabamento}; SHA-256={arquivo_hash[:12]}…"
    )
    registrar_evento(cursor, pedido_id, "Pedido criado", remetente, detalhe)
    conn.commit()
    conn.close()
    return pedido_id, paginas, arquivo_hash


def atualizar_status(pedido_id, novo_status, ator, detalhe_extra=None):
    """Atualiza o status de um pedido, carimba o horário e registra o
    evento na auditoria. Quando o status vira 'Concluído', grava também
    'impresso_em'; quando vira 'Erro', grava o motivo em 'erro_motivo'
    (é o texto que o professor lê na fila, em vez de um "Erro" seco).
    Retorna True se o pedido existia, False caso contrário."""
    agora = agora_iso()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM pedidos WHERE id = ?", (pedido_id,))
    linha = cursor.fetchone()
    if not linha:
        conn.close()
        return False

    if novo_status == "Concluído":
        cursor.execute(
            "UPDATE pedidos SET status = ?, atualizado_em = ?, impresso_em = ?, "
            "erro_motivo = NULL, reservado_em = NULL WHERE id = ?",
            (novo_status, agora, agora, pedido_id)
        )
    elif novo_status == "Erro":
        cursor.execute(
            "UPDATE pedidos SET status = ?, atualizado_em = ?, erro_motivo = ?, "
            "reservado_em = NULL WHERE id = ?",
            (novo_status, agora, detalhe_extra, pedido_id)
        )
    else:
        cursor.execute(
            "UPDATE pedidos SET status = ?, atualizado_em = ? WHERE id = ?",
            (novo_status, agora, pedido_id)
        )

    descricao = f"de '{linha['status']}' para '{novo_status}'"
    if detalhe_extra:
        descricao += f" — {detalhe_extra}"
    registrar_evento(cursor, pedido_id, f"Status: {novo_status}", ator, descricao)
    conn.commit()
    conn.close()
    return True


def reservar_pedido_para_impressao(pedido_id, reserva=None, ator="agente"):
    """RESERVA ATÔMICA E IDEMPOTENTE do pedido para impressão.

    Devolve "reservado" (ganhou a corrida), "sua" (esta mesma reserva já
    valia — a resposta anterior se perdeu na rede), "ocupado" (outro agente
    tem o pedido, ou ele não está mais pendente) ou "inexistente".

    O `UPDATE ... WHERE status='Pendente'` é atômico no SQLite, então dois
    agentes rodando ao mesmo tempo (o mesmo script esquecido em duas
    janelas) não conseguem imprimir o mesmo pedido.

    A IDEMPOTÊNCIA importa tanto quanto a atomicidade: sem ela, uma reserva
    que era gravada mas cuja resposta se perdia fazia a retentativa receber
    409 — o agente desistia, e o pedido ficava 'Imprimindo' sem nada ter
    sido impresso, invisível para a fila do agente até o reaper. Com o
    identificador de reserva, o agente reapresenta o mesmo valor e recebe
    "sua"."""
    agora = agora_iso()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status, reservado_por FROM pedidos WHERE id = ?", (pedido_id,))
    linha = cursor.fetchone()
    if not linha:
        conn.close()
        return "inexistente"

    if linha["status"] == "Imprimindo" and reserva and linha["reservado_por"] == reserva:
        conn.close()
        return "sua"

    cursor.execute(
        "UPDATE pedidos SET status = 'Imprimindo', atualizado_em = ?, reservado_em = ?, "
        "reservado_por = ? WHERE id = ? AND status = 'Pendente'",
        (agora, agora, reserva, pedido_id)
    )
    ganhou = cursor.rowcount == 1
    if ganhou:
        registrar_evento(cursor, pedido_id, "Status: Imprimindo", ator,
                         "reserva atômica a partir de 'Pendente'")
    conn.commit()
    conn.close()
    return "reservado" if ganhou else "ocupado"


def sinalizar_pedidos_presos(minutos=20):
    """Tira do limbo os pedidos que ficaram presos em 'Imprimindo'.

    Se o agente cair entre reservar o pedido e confirmar o resultado — PC
    desligado no fim do dia, queda de energia, Ctrl+C —, nada mais no
    sistema olha para aquele pedido: /api/agente/pendentes só busca
    'Pendente'. Ele ficaria "Imprimindo" para sempre, e o professor
    olhando um status que nunca muda.

    ELE NÃO VOLTA PARA A FILA, e isso é deliberado. Um pedido preso está em
    estado DESCONHECIDO: o papel pode ter saído (o agente entregou ao
    spooler e perdeu a confirmação) ou não. Devolver à fila
    automaticamente resolveria o segundo caso e, no primeiro, faria a
    tiragem inteira sair DE NOVO — meia resma jogada fora, e de novo a
    cada hora enquanto a causa da falha persistisse. Entre desperdiçar
    papel sozinho e pedir uma conferência humana, o certo é o segundo:
    reimprimir é decisão de quem pode olhar a bandeja.

    Então o pedido vira 'Erro' com um motivo que diz a verdade ("não
    sabemos se saiu, confira a bandeja"), fica fora das contagens e
    aparece na fila do professor com instrução clara.

    'minutos' cobre com folga o pior caso legítimo (o timeout do
    SumatraPDF é de 300s, mais a vigia da fila). Retorna quantos foram
    sinalizados."""
    if not minutos or minutos <= 0:
        return 0

    from datetime import timedelta
    corte = (datetime.now(_FUSO) - timedelta(minutes=minutos)).isoformat(timespec="seconds")

    motivo = ("O sistema perdeu contato com a impressora durante este trabalho. "
              "CONFIRA NA BANDEJA se o papel saiu — pode ter saído — e só reenvie se "
              "não tiver saído. Em dúvida, procure o Departamento de T.I.")

    conn = get_connection()
    cursor = conn.cursor()
    # reservado_em é preenchido na reserva, e a migração carimbou os pedidos
    # antigos com o último toque — então a conferência de idade vale para
    # todos, sem exceção que escape do corte (antes, reservado_em NULL
    # passava direto e era sinalizado na primeira inicialização).
    cursor.execute(
        "SELECT id FROM pedidos WHERE status = 'Imprimindo' "
        "AND COALESCE(reservado_em, atualizado_em, criado_em) < ?",
        (corte,)
    )
    ids = [linha["id"] for linha in cursor.fetchall()]

    agora = agora_iso()
    sinalizados = 0
    for pedido_id in ids:
        cursor.execute(
            "UPDATE pedidos SET status = 'Erro', erro_motivo = ?, atualizado_em = ?, "
            "reservado_em = NULL, reservado_por = NULL "
            "WHERE id = ? AND status = 'Imprimindo'",
            (motivo, agora, pedido_id)
        )
        # rowcount 0 = outro processo mexeu no pedido nesse intervalo; não
        # gravamos na auditoria um evento que não aconteceu.
        if cursor.rowcount == 1:
            sinalizados += 1
            registrar_evento(cursor, pedido_id, "Status: Erro", "sistema",
                             f"ficou em 'Imprimindo' por mais de {minutos} min sem confirmação — "
                             "estado desconhecido, NÃO foi reenviado automaticamente")
    conn.commit()
    conn.close()
    return sinalizados


def cancelar_pedido_se_dono(pedido_id, usuario_uid, ator=None):
    """Cancela um pedido AINDA PENDENTE, e só se for do próprio usuário.

    O UPDATE condicional é o que impede cancelar algo que o agente acabou
    de reservar: quem perde a corrida recebe False (e um 409 na rota), não
    um cancelamento falso que deixaria o papel sair de qualquer forma.

    Retorna (True, None) ou (False, motivo)."""
    uid = (usuario_uid or "").strip().lower()
    if not uid:
        return False, "Conta sem identificador — não é possível cancelar."

    agora = agora_iso()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, usuario_uid FROM pedidos WHERE id = ?", (pedido_id,))
    linha = cursor.fetchone()
    if not linha:
        conn.close()
        return False, "Pedido não encontrado."
    if (linha["usuario_uid"] or "").strip().lower() != uid:
        conn.close()
        return False, "Este pedido não é seu."

    cursor.execute(
        "UPDATE pedidos SET status = 'Cancelado', atualizado_em = ? "
        "WHERE id = ? AND status = 'Pendente' AND lower(usuario_uid) = ?",
        (agora, pedido_id, uid)
    )
    if cursor.rowcount != 1:
        conn.close()
        return False, "Este pedido já entrou em impressão e não pode mais ser cancelado."

    registrar_evento(cursor, pedido_id, "Status: Cancelado", ator or uid,
                     "cancelado pelo próprio remetente antes de imprimir")
    conn.commit()
    conn.close()
    return True, None


def pedido_recente_igual(usuario_uid, arquivo_hash, minutos=10):
    """Procura um envio recente do MESMO arquivo pela MESMA conta.

    Serve para o caso clássico: a página demorou, a professora clicou de
    novo, e sairia tudo em dobro. O hash já é calculado no envio, então a
    checagem não custa leitura extra do PDF. Retorna
    {id, status, minutos} ou None."""
    uid = (usuario_uid or "").strip().lower()
    if not uid or not arquivo_hash or not minutos or minutos <= 0:
        return None

    from datetime import timedelta
    corte = (datetime.now(_FUSO) - timedelta(minutes=minutos)).isoformat(timespec="seconds")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, status, criado_em FROM pedidos "
        "WHERE lower(usuario_uid) = ? AND arquivo_hash = ? AND criado_em >= ? "
        "AND status != 'Cancelado' ORDER BY id DESC LIMIT 1",
        (uid, arquivo_hash, corte)
    )
    linha = cursor.fetchone()
    conn.close()
    if not linha:
        return None

    try:
        criado = datetime.fromisoformat(linha["criado_em"])
        decorridos = int((datetime.now(_FUSO) - criado).total_seconds() // 60)
    except (TypeError, ValueError):
        decorridos = 0
    return {"id": linha["id"], "status": linha["status"], "minutos": max(0, decorridos)}


# -------------------------------------------------------------------------
# SINAL DE VIDA DO AGENTE (o modo de falha mais provável do sistema)
# -------------------------------------------------------------------------
_CHAVE_HEARTBEAT = "agente_ultimo_sinal"


def registrar_heartbeat(momento_iso=None):
    """Marca que o agente de impressão está vivo, agora.

    Sem isso, PC da impressora desligado significa pedidos acumulando como
    'Pendente' com todo mundo achando que está tudo bem — e o T.I.
    descobrindo quando um professor reclama, já com uma manhã perdida."""
    momento = momento_iso or agora_iso()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO estado_sistema (chave, valor, atualizado_em) VALUES (?, ?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, "
        "atualizado_em = excluded.atualizado_em",
        (_CHAVE_HEARTBEAT, momento, momento)
    )
    conn.commit()
    conn.close()
    return momento


def ler_heartbeat():
    """Último sinal de vida do agente como texto ISO, ou None se nunca
    houve nenhum (agente antigo, que não manda heartbeat, ou nunca subiu)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM estado_sistema WHERE chave = ?", (_CHAVE_HEARTBEAT,))
    linha = cursor.fetchone()
    conn.close()
    return linha["valor"] if linha else None


def estado_do_agente():
    """(visto_em, segundos) do último sinal do agente — com UMA leitura.

    /api/horario é chamada por toda tela de envio aberta, então não vale
    abrir duas conexões (uma para a data, outra para a idade) quando uma
    resolve. Devolve (None, None) se nunca houve sinal."""
    bruto = ler_heartbeat()
    if not bruto:
        return None, None
    try:
        idade = max(0, int((datetime.now(_FUSO) - datetime.fromisoformat(bruto)).total_seconds()))
    except (TypeError, ValueError):
        return bruto, None
    return bruto, idade


def segundos_desde_heartbeat():
    """Quantos segundos desde o último sinal do agente, ou None se nunca
    houve sinal. É o número que decide se a tela mostra "impressora fora do
    ar" para os professores."""
    return estado_do_agente()[1]


# -------------------------------------------------------------------------
# CONSUMO E RELATÓRIO (garantia/prestação de contas do Departamento)
# -------------------------------------------------------------------------
# Status que NÃO consomem recurso e por isso ficam fora de toda contagem:
# 'Erro' (não saiu papel) e 'Cancelado' (o remetente desistiu antes de
# imprimir). Uma constante só, porque um status novo que os relatórios
# ignoram vira divergência de números entre telas.
_STATUS_FORA_DA_CONTA = ("Erro", "Cancelado")
_SQL_STATUS_CONTA = "status NOT IN ('Erro', 'Cancelado')"


def consumo_mensal_impressoes(usuario_uid, ano_mes):
    """Total de IMPRESSÕES (páginas × cópias — a unidade do toner e do
    contador da Konica) que um usuário gerou em um mês ('YYYY-MM')."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT COALESCE(SUM(COALESCE(paginas, 1) * copias), 0)
        FROM pedidos
        WHERE usuario_uid = ?
          AND substr(criado_em, 1, 7) = ?
          AND {_SQL_STATUS_CONTA}
    ''', (usuario_uid, ano_mes))
    total = cursor.fetchone()[0]
    conn.close()
    return total


def consumo_mensal_folhas(usuario_uid, ano_mes):
    """Total de FOLHAS DE PAPEL que um usuário gerou em um mês ('YYYY-MM').

    É a unidade da cota: folha é o que acaba no armário e o que a escola
    compra. Contar em folhas também faz frente e verso consumir metade da
    cota — a métrica deixa de ser só medição e passa a induzir o
    comportamento que economiza papel.

    Pedido sem 'folhas' gravada (histórico anterior à coluna, que a
    migração já preencheu) entra com o fallback de páginas × cópias, que
    superestima em duplex — erro para o lado seguro do orçamento."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT COALESCE(SUM(COALESCE(folhas, COALESCE(paginas, 1) * copias)), 0)
        FROM pedidos
        WHERE usuario_uid = ?
          AND substr(criado_em, 1, 7) = ?
          AND {_SQL_STATUS_CONTA}
    ''', (usuario_uid, ano_mes))
    total = cursor.fetchone()[0]
    conn.close()
    return total


def _filtro_periodo(filtros, params, data_inicio, data_fim, coluna="criado_em"):
    """Acrescenta o recorte de datas (YYYY-MM-DD, inclusivo) à lista de
    filtros/params. Reaproveitado pelos relatórios."""
    if data_inicio:
        filtros.append(f"substr({coluna}, 1, 10) >= ?")
        params.append(data_inicio)
    if data_fim:
        filtros.append(f"substr({coluna}, 1, 10) <= ?")
        params.append(data_fim)


def _filtro_professor(filtros, params, professor, coluna="professor_nome"):
    """Acrescenta o filtro por nome de professor — comparação
    case-insensitive e com strip(), porque o nome é digitado por gente."""
    if professor and professor.strip():
        filtros.append(f"lower(trim({coluna})) = lower(trim(?))")
        params.append(professor)


def _filtro_segmento(filtros, params, segmento, coluna="segmento"):
    """Acrescenta o filtro por segmento — aceita um código só ou uma lista
    (coordenação que cobre mais de um segmento). Pedidos com segmento NULL
    (envios antigos, de antes desta coluna existir) NUNCA batem aqui — só
    aparecem quando ninguém pede um segmento específico (escopo TUDO). Quem
    decide QUAIS segmentos entram aqui é o chamador (app.py, a partir do
    escopo do usuário) — esta função só aplica o que recebeu."""
    segmentos = normalizar_segmentos(segmento)
    if len(segmentos) == 1:
        filtros.append(f"{coluna} = ?")
        params.append(segmentos[0])
    elif segmentos:
        marcadores = ",".join("?" for _ in segmentos)
        filtros.append(f"{coluna} IN ({marcadores})")
        params.extend(segmentos)


def relatorio_consumo(data_inicio=None, data_fim=None, professor=None, segmento=None):
    """Relatório agregado por usuário para o período (datas 'YYYY-MM-DD'
    inclusivas; se omitidas, pega tudo). Para cada professor traz nº de
    pedidos, total de cópias e total de impressões (páginas × cópias) —
    o documento de consumo que o Departamento usa na prestação de contas.

    'segmento', quando informado, é o PISO de escopo (travado pelo
    chamador) — filtra antes de qualquer outra coisa. 'professor' filtra
    dentro desse piso. Retorna também 'professores_disponiveis': os nomes
    distintos do período dentro do escopo, ANTES do filtro por professor —
    é o que alimenta o dropdown do front sem precisar de uma rota extra."""
    filtros_escopo = [_SQL_STATUS_CONTA]
    params_escopo = []
    _filtro_periodo(filtros_escopo, params_escopo, data_inicio, data_fim)
    _filtro_segmento(filtros_escopo, params_escopo, segmento)
    where_escopo = " WHERE " + " AND ".join(filtros_escopo)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f'''
        SELECT DISTINCT professor_nome FROM pedidos {where_escopo}
        ORDER BY professor_nome COLLATE NOCASE ASC
    ''', params_escopo)
    professores_disponiveis = [l["professor_nome"] for l in cursor.fetchall()]

    filtros = list(filtros_escopo)
    params = list(params_escopo)
    _filtro_professor(filtros, params, professor)
    where = " WHERE " + " AND ".join(filtros)

    cursor.execute(f'''
        SELECT
            professor_nome,
            usuario_uid,
            COUNT(*)                                   AS pedidos,
            COALESCE(SUM(copias), 0)                   AS total_copias,
            COALESCE(SUM(COALESCE(paginas, 0)), 0)     AS total_paginas,
            COALESCE(SUM(COALESCE(paginas, 0) * copias), 0) AS total_impressoes,
            -- FOLHAS DE PAPEL: unidade diferente de "impressões" (que é
            -- por face, e é o que o contrato da Konica cobra). As duas
            -- convivem de propósito — ver docs/API.md.
            COALESCE(SUM(COALESCE(folhas, COALESCE(paginas, 0) * copias)), 0) AS total_folhas
        FROM pedidos
        {where}
        GROUP BY professor_nome, usuario_uid
        ORDER BY total_impressoes DESC
    ''', params)
    linhas = [dict(linha) for linha in cursor.fetchall()]
    conn.close()
    return {"linhas": linhas, "professores_disponiveis": professores_disponiveis}


def relatorio_custos(data_inicio=None, data_fim=None, professor=None, segmento=None):
    """Relatório do Diretor Administrativo: consumo separado em
    Preto-e-Branco × Colorida (para levantamento de custo), com um resumo
    geral e uma quebra por professor. Mesma semântica de 'segmento'
    (piso travado pelo chamador) e 'professor' (filtro dentro do piso) de
    relatorio_consumo."""
    filtros_escopo = [_SQL_STATUS_CONTA]
    params_escopo = []
    _filtro_periodo(filtros_escopo, params_escopo, data_inicio, data_fim)
    _filtro_segmento(filtros_escopo, params_escopo, segmento)
    eh_cor = "lower(cor) LIKE 'color%'"   # 'Colorida'/'Colorido' -> colorido
    # Folhas por linha, com o mesmo fallback usado em toda parte.
    folhas_sql = "COALESCE(folhas, COALESCE(paginas, 0) * copias)"

    conn = get_connection()
    cursor = conn.cursor()

    where_escopo = " WHERE " + " AND ".join(filtros_escopo)
    cursor.execute(f'''
        SELECT DISTINCT professor_nome FROM pedidos {where_escopo}
        ORDER BY professor_nome COLLATE NOCASE ASC
    ''', params_escopo)
    professores_disponiveis = [l["professor_nome"] for l in cursor.fetchall()]

    filtros = list(filtros_escopo)
    params = list(params_escopo)
    _filtro_professor(filtros, params, professor)
    where = " WHERE " + " AND ".join(filtros)

    cursor.execute(f'''
        SELECT
            CASE WHEN {eh_cor} THEN 'Colorida' ELSE 'Preto e Branco' END AS categoria,
            COUNT(*)                                        AS pedidos,
            COALESCE(SUM(copias), 0)                        AS copias,
            COALESCE(SUM(COALESCE(paginas, 0) * copias), 0) AS impressoes,
            COALESCE(SUM({folhas_sql}), 0)                  AS folhas
        FROM pedidos {where}
        GROUP BY categoria
    ''', params)
    por_cor = [dict(l) for l in cursor.fetchall()]

    cursor.execute(f'''
        SELECT
            professor_nome,
            COALESCE(SUM(CASE WHEN {eh_cor} THEN 0 ELSE copias END), 0) AS copias_pb,
            COALESCE(SUM(CASE WHEN {eh_cor} THEN copias ELSE 0 END), 0) AS copias_cor,
            COALESCE(SUM(CASE WHEN {eh_cor} THEN 0 ELSE COALESCE(paginas,0)*copias END), 0) AS impressoes_pb,
            COALESCE(SUM(CASE WHEN {eh_cor} THEN COALESCE(paginas,0)*copias ELSE 0 END), 0) AS impressoes_cor,
            COALESCE(SUM(CASE WHEN {eh_cor} THEN 0 ELSE {folhas_sql} END), 0) AS folhas_pb,
            COALESCE(SUM(CASE WHEN {eh_cor} THEN {folhas_sql} ELSE 0 END), 0) AS folhas_cor
        FROM pedidos {where}
        GROUP BY professor_nome
        ORDER BY (impressoes_pb + impressoes_cor) DESC
    ''', params)
    por_professor = [dict(l) for l in cursor.fetchall()]
    conn.close()
    return {"por_cor": por_cor, "por_professor": por_professor, "professores_disponiveis": professores_disponiveis}


def relatorio_por_materia(data_inicio=None, data_fim=None, professor=None, segmento=None):
    """Relatório da Diretora Pedagógica: os documentos enviados pelos
    docentes, para conferir o que foi mandado em cada matéria. Envios
    institucionais da própria Diretoria ficam de fora (não são matérias).
    Mesma semântica de 'segmento' (piso) e 'professor' (filtro dentro do
    piso) dos outros relatórios."""
    filtros_escopo = [
        "p.status NOT IN ('Erro', 'Cancelado')",
        f"(u.role IS NULL OR u.role NOT IN ('{ROLE_DIRETOR_ADM}', '{ROLE_DIRETORA_PED}'))",
    ]
    params_escopo = []
    _filtro_periodo(filtros_escopo, params_escopo, data_inicio, data_fim, coluna="p.criado_em")
    _filtro_segmento(filtros_escopo, params_escopo, segmento, coluna="p.segmento")

    conn = get_connection()
    cursor = conn.cursor()

    where_escopo = " WHERE " + " AND ".join(filtros_escopo)
    cursor.execute(f'''
        SELECT DISTINCT p.professor_nome
        FROM pedidos p
        LEFT JOIN usuarios_locais u ON u.username = p.usuario_uid
        {where_escopo}
        ORDER BY p.professor_nome COLLATE NOCASE ASC
    ''', params_escopo)
    professores_disponiveis = [l["professor_nome"] for l in cursor.fetchall()]

    filtros = list(filtros_escopo)
    params = list(params_escopo)
    _filtro_professor(filtros, params, professor, coluna="p.professor_nome")
    where = " WHERE " + " AND ".join(filtros)

    cursor.execute(f'''
        SELECT p.id, p.materia, p.professor_nome, p.arquivo_nome, p.copias,
               p.paginas, p.criado_em, p.status, p.arquivo_purgado,
               COALESCE(p.folhas, COALESCE(p.paginas, 0) * p.copias) AS folhas
        FROM pedidos p
        LEFT JOIN usuarios_locais u ON u.username = p.usuario_uid
        {where}
        ORDER BY p.materia COLLATE NOCASE ASC, p.criado_em DESC
    ''', params)
    documentos = [dict(l) for l in cursor.fetchall()]
    conn.close()
    return {"documentos": documentos, "professores_disponiveis": professores_disponiveis}


def obter_arquivo_pedido(pedido_id):
    """Devolve nome/conteúdo/purgado/segmento do PDF de um pedido, ou None.
    Usado tanto pelo agente quanto pela visualização de documentos da
    Diretora Pedagógica e da COORDENACAO (o 'segmento' aqui é o que permite
    a rota decidir se o pedido está dentro do escopo de quem pediu)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT arquivo_nome, arquivo_conteudo, arquivo_purgado, segmento FROM pedidos WHERE id = ?",
        (pedido_id,)
    )
    linha = cursor.fetchone()
    conn.close()
    if not linha:
        return None
    return {
        "nome": linha["arquivo_nome"],
        "conteudo": linha["arquivo_conteudo"],
        "purgado": bool(linha["arquivo_purgado"]),
        "segmento": linha["segmento"],
    }


# -------------------------------------------------------------------------
# RETENÇÃO / LGPD — remove o conteúdo de PDFs antigos já impressos
# -------------------------------------------------------------------------
def purgar_pdfs_antigos(dias):
    """Apaga o CONTEÚDO (BLOB) dos PDFs já concluídos há mais de `dias`,
    mantendo o registro do pedido e seu hash para auditoria. Provas e
    listas são dados sensíveis: guardamos o suficiente para comprovar
    (quem/quando/qual arquivo, pelo hash) e descartamos o conteúdo em si.
    Retorna quantos pedidos tiveram o conteúdo removido. dias <= 0 desliga."""
    if not dias or dias <= 0:
        return 0

    from datetime import timedelta
    corte = (datetime.now(_FUSO) - timedelta(days=dias)).isoformat(timespec="seconds")

    conn = get_connection()
    cursor = conn.cursor()
    # Todo pedido FINALIZADO entra na purga, não só o 'Concluído': PDF de
    # pedido cancelado ou com erro ficava no banco para sempre — são provas
    # e listas de alunos, exatamente o dado que a retenção existe para
    # descartar. 'Pendente'/'Imprimindo' ficam de fora porque o agente
    # ainda vai precisar do arquivo.
    cursor.execute('''
        SELECT id FROM pedidos
        WHERE status IN ('Concluído', 'Cancelado', 'Erro')
          AND arquivo_purgado = 0
          AND criado_em IS NOT NULL
          AND criado_em < ?
    ''', (corte,))
    ids = [linha["id"] for linha in cursor.fetchall()]

    for pedido_id in ids:
        # Gravamos um blob VAZIO (não NULL): bancos criados na versão antiga
        # têm 'arquivo_conteudo BLOB NOT NULL', e a migração não remove essa
        # restrição. Quem marca o pedido como purgado é a coluna própria.
        cursor.execute(
            "UPDATE pedidos SET arquivo_conteudo = X'', arquivo_purgado = 1 WHERE id = ?",
            (pedido_id,)
        )
        registrar_evento(cursor, pedido_id, "Arquivo removido (retenção)",
                          "sistema", f"conteúdo descartado após {dias} dias")

    conn.commit()
    conn.close()
    return len(ids)
