import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { AlertCircle, Lock, ShieldCheck } from "lucide-react";
import { Role, SENHA_MINIMA } from "./types";
import { API_BASE_URL } from "../config";

const SESSION_KEY = "acalanto_session";
// O login Google foi removido: o sistema roda em uma VM sem o fluxo OAuth
// do Workspace. O acesso é só por conta local (usuário/senha do servidor).
export type Session = {
  name: string;
  role: Role;
  method: "local";
  isSuperAdmin?: boolean;
  token: string;
  // Segmento CADASTRADO da conta (não o escopo de visão — esse vem de
  // /api/fila). Só serve pra pré-preencher o formulário de envio; vem
  // preenchido apenas quando a conta tem UM segmento.
  segmento?: string | null;
  // Todos os segmentos cadastrados — a conta pode participar de mais de um
  // (coordenador de área que dá aula em dois segmentos). Sessões salvas
  // antes desta lista existir não têm o campo; quem lê trata a ausência.
  segmentos?: string[];
};
type Props = { onLogin: (session: Session) => void };

export function saveSession(session: Session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

/** Substitui só o token da sessão guardada, mantendo o resto.
 *
 * Usado depois de trocar a senha: a troca incrementa o token_version no
 * servidor e DERRUBA o token atual (é isso que revoga as outras sessões).
 * Sem guardar o token novo que o servidor devolve, quem acabou de trocar a
 * senha seria deslogado no próximo clique. */
export function atualizarTokenDaSessao(token: string) {
  const atual = getStoredSession();
  if (!atual || !token) return;
  saveSession({ ...atual, token });
}

export function getStoredSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

export function LoginScreen({ onLogin }: Props) {
  const [username, setUsername] = useState(() => localStorage.getItem("acalanto_last_user") ?? "");
  const [pass, setPass] = useState("");
  const [error, setError] = useState("");
  // "login" mostra o formulário de entrada; "registrar" mostra o de
  // auto-cadastro (sempre como Coordenador — o cargo só muda depois, no
  // painel do Departamento de T.I.).
  const [modo, setModo] = useState<"login" | "registrar">("login");
  const [nome, setNome] = useState("");

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!nome.trim() || !username.trim() || !pass) {
      setError("Preencha nome, usuário e senha.");
      return;
    }
    if (pass.length < SENHA_MINIMA) {
      setError(`A senha precisa ter pelo menos ${SENHA_MINIMA} caracteres.`);
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/api/registrar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nome.trim(), username: username.trim(), password: pass }),
      });
      const data = await response.json();
      if (response.ok && data.status === "sucesso") {
        localStorage.setItem("acalanto_last_user", username.trim());
        const session: Session = {
          name: data.name,
          role: data.role as Role,
          method: "local",
          isSuperAdmin: data.isSuperAdmin === true,
          token: data.token,
          segmento: data.segmento ?? null,
          segmentos: Array.isArray(data.segmentos) ? data.segmentos : (data.segmento ? [data.segmento] : []),
        };
        saveSession(session);
        onLogin(session);
      } else {
        setError(data.erro || "Não foi possível criar a conta.");
      }
    } catch (err) {
      setError("Erro ao conectar com o servidor local.");
    }
  };

  const handleLocalLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!username.trim() || !pass) {
      setError("Por favor, preencha todos os campos.");
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/api/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password: pass }),
      });
      const data = await response.json();
      if (response.ok && data.status === "sucesso") {
        localStorage.setItem("acalanto_last_user", username.trim());
        const session: Session = {
          name: data.name,
          role: data.role as Role,
          method: "local",
          isSuperAdmin: data.isSuperAdmin === true,
          token: data.token,
          segmento: data.segmento ?? null,
          segmentos: Array.isArray(data.segmentos) ? data.segmentos : (data.segmento ? [data.segmento] : []),
        };
        saveSession(session);
        onLogin(session);
      } else {
        setError(data.erro || "Usuário ou senha incorretos.");
      }
    } catch (err) {
      setError("Erro ao conectar com o servidor local.");
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[var(--brand-slate)] p-6">
        <div className="w-full max-w-5xl grid md:grid-cols-2 rounded-2xl overflow-hidden shadow-xl border border-[var(--brand-border)] bg-white">
          
          {/* Painel Esquerdo Visual */}
          <div className="relative hidden md:flex flex-col justify-between p-10 bg-[var(--brand-blue)] text-white overflow-hidden">
            <div className="absolute inset-0 opacity-20">
              <svg viewBox="0 0 400 400" className="w-full h-full">
                <circle cx="80" cy="80" r="120" fill="white" />
                <circle cx="320" cy="340" r="160" fill="white" opacity="0.6" />
              </svg>
            </div>
            <div className="relative z-10">
              <div className="w-16 h-16 rounded-xl bg-white text-[var(--brand-blue)] flex items-center justify-center font-bold text-2xl">IA</div>
            </div>
            <div className="relative z-10">
              <p className="text-2xl font-semibold leading-tight">Portal de Gerenciamento de Impressão</p>
              <p className="mt-2 opacity-80">Instituto Acalanto de Ensino</p>
              <div className="mt-6 flex items-center gap-2 opacity-80">
                <ShieldCheck size={18} />
                <span className="text-sm">Acesso restrito · Servidor local</span>
              </div>
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--brand-red)]" />
          </div>

          {/* Painel Direito (Formulário de acesso local) */}
          <div className="p-8 md:p-12 flex flex-col justify-center">
            <div className="mb-6">
              <p className="text-[var(--brand-blue)] text-xs font-bold tracking-widest">SESSÃO RESTRITA</p>
              <h1 className="mt-1 text-2xl font-bold text-slate-900">Instituto Acalanto de Ensino</h1>
              <p className="text-slate-500 mt-1">
                {modo === "login"
                  ? "Entre com seu usuário e senha do servidor local."
                  : "Crie sua conta de acesso ao portal."}
              </p>
            </div>

            <form onSubmit={modo === "login" ? handleLocalLogin : handleRegister} className="space-y-4">
              {modo === "registrar" && (
                <div className="space-y-2">
                  <Label htmlFor="nome">Nome completo</Label>
                  <Input
                    id="nome"
                    value={nome}
                    onChange={(e) => { setNome(e.target.value); setError(""); }}
                    placeholder="Ex: Marcos Souza"
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="user">Usuário do servidor local</Label>
                <Input
                  id="user"
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError(""); }}
                  placeholder="usuario.local"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pass">Senha</Label>
                <Input
                  id="pass"
                  type="password"
                  value={pass}
                  onChange={(e) => { setPass(e.target.value); setError(""); }}
                  placeholder="••••••••"
                />
              </div>

              {modo === "registrar" && (
                <div className="flex items-start gap-2 rounded-md bg-blue-50 border border-blue-200 px-3 py-2.5">
                  <ShieldCheck size={15} className="text-[var(--brand-blue)] mt-0.5 flex-shrink-0" />
                  <p className="text-slate-600 text-xs">
                    Sua conta será criada como <strong>Coordenador</strong>. O acesso de
                    Departamento de T.I. é concedido depois pela própria equipe de T.I.
                  </p>
                </div>
              )}

              {error && (
                <div className="flex items-start gap-2 rounded-md bg-red-50 border border-red-200 px-3 py-2.5">
                  <AlertCircle size={15} className="text-[var(--brand-red)] mt-0.5 flex-shrink-0" />
                  <p className="text-red-700 text-xs">{error}</p>
                </div>
              )}

              <Button type="submit" className="w-full h-11 bg-[var(--brand-blue)] hover:bg-[var(--brand-blue-hover)] text-white transition">
                <Lock size={16} className="mr-2" />
                {modo === "login" ? "Entrar com Credenciais do Servidor Local" : "Criar conta e entrar"}
              </Button>

              <button
                type="button"
                onClick={() => { setModo(modo === "login" ? "registrar" : "login"); setError(""); }}
                className="w-full text-center text-sm text-[var(--brand-blue)] hover:underline"
              >
                {modo === "login" ? "Não tem conta? Criar conta" : "Já tem conta? Entrar"}
              </button>
            </form>
          </div>

        </div>
    </div>
  );
}
