import { useEffect, useState } from "react";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Badge } from "./ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { ChevronDown, KeyRound, ShieldCheck, Trash2, UserPlus, Users, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { Role, SEGMENTOS_VALIDOS, ROTULOS_SEGMENTO, SENHA_MINIMA, normalizarSegmentos, rotuloSegmentos } from "./types";
import { getStoredSession, clearSession } from "./LoginScreen";
import { API_BASE_URL } from "../config";

type UsuarioLocal = {
  username: string;
  name: string;
  role: Role;
  isSuperAdmin: boolean;
  segmento: string | null;
  // Lista completa — a conta pode participar de mais de um segmento
  // (coordenador de área que dá aula em dois). `segmento` fica como o
  // texto cru da coluna, só para respostas antigas do servidor.
  segmentos?: string[];
};

// Segmentos cadastrados de uma conta, aceitando resposta antiga (só
// `segmento`) e nova (`segmentos`).
const segmentosDaConta = (u: UsuarioLocal) =>
  normalizarSegmentos(u.segmentos && u.segmentos.length > 0 ? u.segmentos : u.segmento);

const CARGO_LABEL: Record<Role, string> = {
  COORDENADOR: "Coordenador",
  COORDENACAO: "Coordenação de Segmento",
  DIRETOR_ADM: "Diretor Administrativo",
  DIRETORA_PED: "Diretora Pedagógica",
  TI: "Departamento de T.I.",
};

const CARGO_BADGE: Record<Role, string> = {
  COORDENADOR: "bg-slate-50 text-slate-700 border-slate-200",
  COORDENACAO: "bg-amber-50 text-amber-700 border-amber-200",
  DIRETOR_ADM: "bg-violet-50 text-violet-700 border-violet-200",
  DIRETORA_PED: "bg-violet-50 text-violet-700 border-violet-200",
  TI: "bg-blue-50 text-blue-700 border-blue-200",
};

// Papéis onde o segmento importa de verdade (professor: pré-preenche o
// formulário; coordenação: define o escopo de visão). Para Diretoria/T.I.
// o campo não tem efeito nenhum — não faz sentido destacar como "faltando".
const PAPEIS_COM_SEGMENTO: Role[] = ["COORDENADOR", "COORDENACAO"];

// Seletor de VÁRIOS segmentos (dropdown com caixas de marcar): quem dá aula
// em mais de um segmento é cadastrado com todos eles. O menu não fecha ao
// marcar (onSelect prevenido) para dar pra marcar vários de uma vez.
function SegmentosSelect({ value, onChange, className }: {
  value: string[];
  onChange: (segmentos: string[]) => void;
  className?: string;
}) {
  const alternar = (codigo: string, marcado: boolean) =>
    onChange(normalizarSegmentos(marcado ? [...value, codigo] : value.filter((s) => s !== codigo)));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" className={`justify-between font-normal ${className ?? ""}`}>
          <span className="truncate">{value.length > 0 ? rotuloSegmentos(value) : "Não definido"}</span>
          <ChevronDown size={14} className="opacity-50 shrink-0" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {SEGMENTOS_VALIDOS.map((s) => (
          <DropdownMenuCheckboxItem
            key={s}
            checked={value.includes(s)}
            onCheckedChange={(marcado) => alternar(s, marcado === true)}
            onSelect={(e) => e.preventDefault()}
          >
            {ROTULOS_SEGMENTO[s]}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AdminUsersPanel() {
  const [usuarios, setUsuarios] = useState<UsuarioLocal[]>([]);
  const [loading, setLoading] = useState(false);

  // Formulário de criação direta pelo TI.
  const [novoNome, setNovoNome] = useState("");
  const [novoUser, setNovoUser] = useState("");
  const [novaSenha, setNovaSenha] = useState("");
  const [novoRole, setNovoRole] = useState<Role>("COORDENADOR");
  const [novosSegmentos, setNovosSegmentos] = useState<string[]>([]);

  // Rascunho local dos segmentos por usuário: cada clique no seletor parte
  // do que está NA TELA, não do último estado carregado do servidor — sem
  // isso, marcar duas caixas rápido faria o segundo POST (calculado sobre a
  // lista antiga) desfazer o primeiro. O rascunho é limpo quando a lista
  // recarrega (o servidor volta a ser a verdade) ou quando o POST falha.
  const [segmentosRascunho, setSegmentosRascunho] = useState<Record<string, string[]>>({});

  const authHeaders = () => {
    const session = getStoredSession();
    return { Authorization: `Bearer ${session?.token ?? ""}` };
  };

  const carregar = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/usuarios`, { headers: authHeaders() });
      if (response.status === 401) {
        toast.error("Sua sessão expirou. Entre novamente.");
        clearSession();
        window.location.reload();
        return;
      }
      if (!response.ok) {
        toast.error("Não foi possível carregar os usuários.");
        return;
      }
      const data = await response.json();
      setUsuarios(data.usuarios ?? []);
      setSegmentosRascunho({});
    } catch {
      toast.error("Erro ao comunicar com o servidor.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Helper genérico para as ações POST de administração.
  const acao = async (url: string, body: object | null, sucesso: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}${url}`, {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.status === "sucesso") {
        toast.success(sucesso);
        carregar();
        return true;
      }
      toast.error(data.erro || "Não foi possível concluir a ação.");
      return false;
    } catch {
      toast.error("Erro ao comunicar com o servidor.");
      return false;
    }
  };

  const criar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!novoNome.trim() || !novoUser.trim() || novaSenha.length < SENHA_MINIMA) {
      toast.error(`Preencha nome, usuário e uma senha de pelo menos ${SENHA_MINIMA} caracteres.`);
      return;
    }
    const ok = await acao("/api/admin/usuarios",
      {
        name: novoNome.trim(), username: novoUser.trim(), password: novaSenha, role: novoRole,
        segmentos: novosSegmentos,
      },
      "Usuário criado.");
    if (ok) { setNovoNome(""); setNovoUser(""); setNovaSenha(""); setNovoRole("COORDENADOR"); setNovosSegmentos([]); }
  };

  const definirCargo = (u: UsuarioLocal, novo: Role) => {
    if (novo === u.role) return;
    acao(`/api/admin/usuarios/${encodeURIComponent(u.username)}/role`, { role: novo },
      `${u.name} agora é ${CARGO_LABEL[novo]}.`);
  };

  const definirSegmentos = (u: UsuarioLocal, novos: string[]) => {
    const lista = normalizarSegmentos(novos);
    setSegmentosRascunho((r) => ({ ...r, [u.username]: lista }));
    acao(`/api/admin/usuarios/${encodeURIComponent(u.username)}/segmento`, { segmentos: lista },
      `Segmento de ${u.name} atualizado.`).then((ok) => {
        if (!ok) {
          // POST recusado: solta o rascunho e volta a mostrar o que o
          // servidor tem de verdade.
          setSegmentosRascunho((r) => {
            const { [u.username]: _descartado, ...resto } = r;
            return resto;
          });
        }
      });
  };

  const resetarSenha = (u: UsuarioLocal) => {
    const nova = window.prompt(`Nova senha para ${u.name} (mín. ${SENHA_MINIMA} caracteres):`);
    if (nova === null) return;
    if (nova.length < SENHA_MINIMA) {
      toast.error(`A senha precisa ter pelo menos ${SENHA_MINIMA} caracteres.`);
      return;
    }
    acao(`/api/admin/usuarios/${encodeURIComponent(u.username)}/senha`, { password: nova },
      "Senha redefinida.");
  };

  const remover = (u: UsuarioLocal) => {
    if (!window.confirm(`Remover a conta de ${u.name} (${u.username})? Esta ação não pode ser desfeita.`)) return;
    acao(`/api/admin/usuarios/${encodeURIComponent(u.username)}/remover`, null, "Usuário removido.");
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a" }}>
          Usuários do Sistema
        </h1>
        <p className="text-slate-500 mt-1">
          Defina o cargo de cada conta (Coordenador, Diretoria ou T.I.), redefina senhas e gerencie as contas locais.
        </p>
      </div>

      {/* Criação direta pelo TI */}
      <Card className="p-6 border-[var(--brand-border)] shadow-sm">
        <div className="flex items-center gap-2 mb-4">
          <UserPlus size={18} className="text-[var(--brand-blue)]" />
          <h2 style={{ fontSize: "1.1rem", fontWeight: 600, color: "#0f172a" }}>Cadastrar novo usuário</h2>
        </div>
        <form onSubmit={criar} className="grid md:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
          <div className="space-y-2">
            <Label htmlFor="n-nome">Nome completo</Label>
            <Input id="n-nome" value={novoNome} onChange={(e) => setNovoNome(e.target.value)} placeholder="Marcos Souza" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="n-user">Usuário</Label>
            <Input id="n-user" value={novoUser} onChange={(e) => setNovoUser(e.target.value)} placeholder="marcos.s" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="n-senha">Senha</Label>
            <Input id="n-senha" type="password" value={novaSenha} onChange={(e) => setNovaSenha(e.target.value)} placeholder="••••••••" />
          </div>
          <div className="space-y-2">
            <Label>Cargo</Label>
            <Select value={novoRole} onValueChange={(v) => setNovoRole(v as Role)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="COORDENADOR">Coordenador</SelectItem>
                <SelectItem value="COORDENACAO">Coordenação de Segmento</SelectItem>
                <SelectItem value="DIRETOR_ADM">Diretor Administrativo</SelectItem>
                <SelectItem value="DIRETORA_PED">Diretora Pedagógica</SelectItem>
                <SelectItem value="TI">Departamento de T.I.</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Segmento(s)</Label>
            <SegmentosSelect value={novosSegmentos} onChange={setNovosSegmentos} className="w-full h-10" />
          </div>
          <Button type="submit" className="bg-[var(--brand-blue)] hover:bg-[var(--brand-blue-hover)] text-white h-10 lg:col-span-1">
            Cadastrar
          </Button>
        </form>
      </Card>

      {/* Lista de usuários */}
      <Card className="border-[var(--brand-border)] overflow-hidden">
        <div className="px-6 py-4 border-b border-[var(--brand-border)] flex items-center gap-2">
          <Users size={16} className="text-slate-500" />
          <p style={{ fontWeight: 600, color: "#0f172a" }}>
            {loading ? "Carregando..." : `${usuarios.length} conta(s) local(is)`}
          </p>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Nome</TableHead>
                <TableHead>Usuário</TableHead>
                <TableHead>Cargo</TableHead>
                <TableHead>Segmento</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usuarios.map((u) => {
                const segmentosConta = segmentosRascunho[u.username] ?? segmentosDaConta(u);
                const faltaSegmento = PAPEIS_COM_SEGMENTO.includes(u.role) && segmentosConta.length === 0;
                return (
                <TableRow key={u.username} className={`hover:bg-slate-50/50 ${faltaSegmento ? "bg-amber-50/60" : ""}`}>
                  <TableCell style={{ fontWeight: 500 }}>
                    {u.name}
                    {u.isSuperAdmin && (
                      <Badge variant="outline" className="ml-2 bg-amber-50 text-amber-700 border-amber-200">
                        <ShieldCheck size={12} className="mr-1" /> Admin
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-slate-500" style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.8rem" }}>
                    {u.username}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={CARGO_BADGE[u.role]}>
                      {CARGO_LABEL[u.role]}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {faltaSegmento ? (
                      <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200">
                        <AlertTriangle size={12} className="mr-1" /> Não definido
                      </Badge>
                    ) : (
                      <span className="text-slate-600" style={{ fontSize: "0.85rem" }}>{rotuloSegmentos(segmentosConta)}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end items-center gap-2 flex-wrap">
                      <Select value={u.role} onValueChange={(v) => definirCargo(u, v as Role)}>
                        <SelectTrigger className="h-9 w-[185px]"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="COORDENADOR">Coordenador</SelectItem>
                          <SelectItem value="COORDENACAO">Coordenação de Segmento</SelectItem>
                          <SelectItem value="DIRETOR_ADM">Diretor Administrativo</SelectItem>
                          <SelectItem value="DIRETORA_PED">Diretora Pedagógica</SelectItem>
                          <SelectItem value="TI">Departamento de T.I.</SelectItem>
                        </SelectContent>
                      </Select>
                      <SegmentosSelect
                        value={segmentosConta}
                        onChange={(novos) => definirSegmentos(u, novos)}
                        className="h-9 w-[170px]"
                      />
                      <Button size="sm" variant="ghost" onClick={() => resetarSenha(u)} className="gap-1 text-slate-600">
                        <KeyRound size={14} /> Senha
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => remover(u)} className="gap-1 text-[var(--brand-red)]">
                        <Trash2 size={14} /> Remover
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
                );
              })}
              {usuarios.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-slate-500 py-8">
                    Nenhuma conta local cadastrada.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}
