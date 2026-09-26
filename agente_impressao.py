"""
agente_impressao.py

Este script roda NO COMPUTADOR DO COLÉGIO.
Ele é o único componente do sistema com acesso à impressora física.

O que ele faz, em loop:
  1. Pergunta ao site se existe algum pedido
     "Pendente" — só faz isso dentro do horário permitido (ver
     horario_impressao.py; configurável pelo agente.env).
  2. Para cada pedido encontrado, baixa o PDF e dispara a impressão usando
     o automacao_impressora.py já existente.
  3. Avisa o site se deu certo ("Concluído") ou se falhou ("Erro").

Fora do horário de impressão, ele simplesmente não faz nada no ciclo —
os pedidos continuam aparecendo como "Pendente" até o horário abrir de
novo, e são processados na ordem de chegada.
"""

import os
import time as time_module

import requests
from dotenv import load_dotenv

import horario_impressao  # Faixa de horário, compartilhada com o app.py.
from automacao_impressora import disparar_impressao_windows

# Carrega especificamente "agente.env" (não ".env") — assim, se este script
# e o app.py estiverem na mesma pasta durante testes locais, os dois
# arquivos de configuração nunca se confundem.
load_dotenv("agente.env")

# ---------------------------------------------------------------------
# CONFIGURAÇÃO (vem do .env deste mesmo computador — ver agente.env.example)
# ---------------------------------------------------------------------
CLOUD_URL = os.environ.get("CLOUD_URL", "").rstrip("/")
AGENTE_API_KEY = os.environ.get("AGENTE_API_KEY", "")
INTERVALO_SEGUNDOS = int(os.environ.get("AGENTE_INTERVALO_SEGUNDOS", "15"))

# A faixa de horário vem de horario_impressao.py (configurável pelo
# agente.env). Precisa bater com a do .env do servidor: é o app.py que
# promete ao professor a que horas o pedido vai sair.

PASTA_TEMPORARIA = "temp_impressao"


def cabecalhos():
    return {"Authorization": f"Bearer {AGENTE_API_KEY}"}


def dentro_do_horario_de_impressao():
    return horario_impressao.dentro_do_horario()


def buscar_pendentes():
    resposta = requests.get(f"{CLOUD_URL}/api/agente/pendentes", headers=cabecalhos(), timeout=10)
    resposta.raise_for_status()
    return resposta.json().get("pedidos", [])


def baixar_arquivo(pedido_id):
    resposta = requests.get(f"{CLOUD_URL}/api/agente/arquivo/{pedido_id}", headers=cabecalhos(), timeout=30)
    resposta.raise_for_status()
    return resposta.content


def atualizar_status(pedido_id, novo_status):
    requests.post(
        f"{CLOUD_URL}/api/agente/status/{pedido_id}",
        headers=cabecalhos(),
        json={"status": novo_status},
        timeout=10,
    )


def processar_pedido(pedido):
    pedido_id = pedido["id"]
    print(f"[Agente] Processando pedido #{pedido_id} — {pedido['professor_nome']} ({pedido['materia']})")

    # O download vem ANTES de marcar "Imprimindo": o status só deve mudar
    # quando houver o que imprimir, senão o professor vê o pedido "saindo"
    # e caindo em "Erro" sem nada ter sido enviado.
    #
    # Isso conta com um agente só, processando em série — é o que impede
    # dois agentes de pegarem o mesmo pedido nessa janela. Com dois, a
    # reserva precisaria ser explícita no servidor.
    try:
        conteudo_pdf = baixar_arquivo(pedido_id)
    except Exception as e:
        print(f"[Agente] Erro ao baixar arquivo do pedido #{pedido_id}: {e}")
        atualizar_status(pedido_id, "Erro")
        return

    atualizar_status(pedido_id, "Imprimindo")

    os.makedirs(PASTA_TEMPORARIA, exist_ok=True)
    caminho_temporario = os.path.join(PASTA_TEMPORARIA, f"{pedido_id}.pdf")
    with open(caminho_temporario, "wb") as arquivo:
        arquivo.write(conteudo_pdf)

    try:
        sucesso = disparar_impressao_windows(
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
        print(f"[Agente] Pedido #{pedido_id} entregue à impressora.")
        atualizar_status(pedido_id, "Concluído")
    else:
        print(f"[Agente] Pedido #{pedido_id} falhou ao imprimir.")
        atualizar_status(pedido_id, "Erro")


def loop_principal():
    print(f"[Agente] Iniciado. Consultando {CLOUD_URL} a cada {INTERVALO_SEGUNDOS}s.")
    horario_impressao.avisar_se_desenvolvimento("agente_impressao.py")
    print(f"[Agente] Horário de impressão: {horario_impressao.descricao()}.")

    while True:
        try:
            if dentro_do_horario_de_impressao():
                for pedido in buscar_pendentes():
                    processar_pedido(pedido)
            else:
                print("[Agente] Fora do horário de impressão — aguardando.")
        except Exception as e:
            print(f"[Agente] Erro no ciclo (tentando de novo no próximo intervalo): {e}")

        time_module.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    if not CLOUD_URL:
        raise SystemExit("Defina CLOUD_URL no .env deste computador (veja agente.env.example).")
    if not AGENTE_API_KEY:
        raise SystemExit("Defina AGENTE_API_KEY no .env deste computador (veja agente.env.example).")
    loop_principal()
