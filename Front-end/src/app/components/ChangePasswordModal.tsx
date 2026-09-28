import { useState } from "react";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { KeyRound, Loader2, AlertCircle } from "lucide-react";
import { API_BASE_URL } from "../config";
import { getStoredSession, atualizarTokenDaSessao } from "./LoginScreen";
import { SENHA_MINIMA } from "./types";

type Props = {
  open: boolean;
  onClose: () => void;
  onSuccess: (mensagem: string) => void;
};

// Mesmo mínimo exigido pelo servidor (/api/senha) e pelo auto-cadastro.
// Validar aqui é só cortesia: quem manda é o backend.
const MINIMO = SENHA_MINIMA;

export function ChangePasswordModal({ open, onClose, onSuccess }: Props) {
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [confirmacao, setConfirmacao] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  const limpar = () => {
    setAtual("");
    setNova("");
    setConfirmacao("");
    setErro("");
  };

  const fechar = () => {
    if (enviando) return;
    limpar();
    onClose();
  };

  const enviar = async () => {
    setErro("");

    // A confirmação existe só no cliente — o servidor recebe uma senha nova
    // apenas. Errar a digitação e so descobrir no proximo login seria pior.
    if (nova !== confirmacao) {
      setErro("A nova senha e a confirmação não são iguais.");
      return;
    }
    if (nova.length < MINIMO) {
      setErro(`A nova senha precisa ter pelo menos ${MINIMO} caracteres.`);
      return;
    }

    const session = getStoredSession();
    if (!session?.token) {
      setErro("Sua sessão expirou. Entre novamente.");
      return;
    }

    setEnviando(true);
    try {
      const resposta = await fetch(`${API_BASE_URL}/api/senha`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
        },
        body: JSON.stringify({ senha_atual: atual, nova_senha: nova }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (!resposta.ok) {
        setErro(dados.erro || "Não foi possível trocar a senha.");
        return;
      }

      // A troca derrubou o token que esta aba estava usando (é assim que as
      // OUTRAS sessões da conta caem). O servidor devolve um token novo —
      // guardá-lo é o que mantém esta pessoa trabalhando sem refazer login.
      if (dados.token) atualizarTokenDaSessao(dados.token);

      limpar();
      onClose();
      onSuccess("Senha alterada. As outras sessões desta conta foram encerradas.");
    } catch {
      setErro("Não foi possível falar com o servidor.");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && fechar()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-50 border border-blue-100 text-[var(--brand-blue)] flex items-center justify-center">
              <KeyRound size={20} />
            </div>
            <DialogTitle style={{ fontSize: "1.25rem" }}>Trocar Senha</DialogTitle>
          </div>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            enviar();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="senha-atual">Senha atual</Label>
            <Input
              id="senha-atual"
              type="password"
              autoComplete="current-password"
              value={atual}
              onChange={(e) => setAtual(e.target.value)}
              disabled={enviando}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="senha-nova">Nova senha</Label>
            <Input
              id="senha-nova"
              type="password"
              autoComplete="new-password"
              value={nova}
              onChange={(e) => setNova(e.target.value)}
              disabled={enviando}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="senha-confirmacao">Repita a nova senha</Label>
            <Input
              id="senha-confirmacao"
              type="password"
              autoComplete="new-password"
              value={confirmacao}
              onChange={(e) => setConfirmacao(e.target.value)}
              disabled={enviando}
            />
          </div>

          {erro && (
            <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-red-700">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span style={{ fontSize: "0.875rem" }}>{erro}</span>
            </div>
          )}

          <p className="text-slate-500" style={{ fontSize: "0.8rem", lineHeight: 1.5 }}>
            Você continua conectado depois de trocar. Se entrou em outro
            computador, aquela sessão só cai quando expirar.
          </p>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={fechar} disabled={enviando}>
              Cancelar
            </Button>
            <Button type="submit" disabled={enviando || !atual || !nova || !confirmacao}>
              {enviando ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Salvando…
                </>
              ) : (
                "Salvar nova senha"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
