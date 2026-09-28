import { useEffect, useState } from "react";
import { Toaster } from "./components/ui/sonner";
import { toast } from "sonner";
import { LoginScreen, getStoredSession, clearSession, Session } from "./components/LoginScreen";
import { TopNavbar } from "./components/TopNavbar";
import { SubmissionForm, SubmissionDraft } from "./components/SubmissionForm";
import { SubmissionFormDiretoria } from "./components/SubmissionFormDiretoria";
import { InfoSidebar } from "./components/InfoSidebar";
import { ConfirmationModal } from "./components/ConfirmationModal";
import { ChangePasswordModal } from "./components/ChangePasswordModal";
import { QueueMetricsCards } from "./components/QueueMetricsCards";
import { PrintQueueTable } from "./components/PrintQueueTable";
import { ReportsPanel } from "./components/ReportsPanel";
import { AdminUsersPanel } from "./components/AdminUsersPanel";
import { JobStatus, PrintJob, Role, isDiretoria, podeVerRelatorios, rotuloSegmento } from "./components/types";
import { API_BASE_URL } from "./config";

type View = "login" | "dashboard" | "queue" | "report" | "admin";

// O que /api/fila devolve em "escopo" — resolvido pelo SERVIDOR a partir do
// token, nunca calculado aqui. O front só usa isso pra título/subtítulo;
// os dados em si já vêm filtrados independente do que este estado diz.
type EscopoFila = {
  tipo: "TUDO" | "SEGMENTO" | "PROPRIO";
  // 'segmento' vem preenchido só quando o escopo cobre UM segmento; uma
  // coordenação pode cobrir vários — aí quem descreve o recorte é a lista
  // 'segmentos' e o 'segmento_rotulo' já juntado pelo servidor.
  segmento: string | null;
  segmentos?: string[];
  segmento_rotulo: string | null;
};

export default function App() {
  const [view, setView] = useState<View>("login");
  const [role, setRole] = useState<Role>("COORDENADOR");
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [currentUser, setCurrentUser] = useState("");
  const [escopo, setEscopo] = useState<EscopoFila | null>(null);
  const [jobs, setJobs] = useState<PrintJob[]>([]);
  const [draft, setDraft] = useState<SubmissionDraft | null>(null);
  const [formResetKey, setFormResetKey] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [trocandoSenha, setTrocandoSenha] = useState(false);

  // 1. VERIFICA SESSÃO
  useEffect(() => {
    const session = getStoredSession();
    if (session) {
      setCurrentUser(session.name);
      setRole(session.role);
      setIsSuperAdmin(session.isSuperAdmin === true);
      setView("dashboard");
      carregarFila(session.role);
    }
  }, []);

  // 2. BUSCAR FILA REAL NO BACKEND
  const carregarFila = async (roleOverride?: Role) => {
    try {
      const session = getStoredSession();
      if (!session?.token) return;

      // A identidade vem do token assinado; só mandamos qual MODO o Admin
      // quer visualizar (TI ou Coordenador) — o backend ignora isso para
      // quem não é super admin.
      const modoVisualizacao = roleOverride ?? session.role;
      const url = `${API_BASE_URL}/api/fila?view_mode=${encodeURIComponent(modoVisualizacao)}`;

      const response = await fetch(url, {
        method: "GET",
        headers: { Authorization: `Bearer ${session.token}` },
      });

      // Token expirado ou inválido: encerra a sessão e volta ao login.
      if (response.status === 401) {
        handleLogout();
        toast.error("Sua sessão expirou. Entre novamente.");
        return;
      }

      if (!response.ok) {
        // Falha que não é sessão expirada: avisar em vez de deixar a tela
        // congelada em dados antigos parecendo atualizada.
        toast.error("Não foi possível atualizar a fila. Tentando de novo em instantes.");
        return;
      }

      {
        const data = await response.json();

        const filaFormatada: PrintJob[] = data.pedidos.map((p: any) => ({
          id: p.id.toString(),
          sender: p.remetente,
          // Campos separados desde que matéria e turma viraram caixas de
          // seleção. O `materia_turma` continua vindo do servidor, mas só
          // serve de reserva: separá-lo pelo " — " errava quando o próprio
          // texto de "Outro" trazia o separador.
          subject: p.materia || p.materia_turma?.split(' — ')[0] || "Geral",
          turma: p.turma || p.materia_turma?.split(' — ')[1] || "-",
          fileName: p.arquivo,
          copies: p.copias,
          pages: p.paginas ?? null,
          // Valores REAIS do pedido (antes eram fixos aqui, porque a fila
          // não os devolvia). O servidor manda booleanos já normalizados —
          // o banco tem as duas formas históricas de "frente e verso".
          color: p.colorida ? "Colorida" : "PB",
          pageMode: p.duplex ? "FrenteVerso" : "Frente",
          finishing: p.grampeada ? "Grampeada" : "Normal",
          status: p.status as JobStatus,
          // Datas reais carimbadas pelo servidor (não mais Date.now()).
          submittedAt: p.criado_em ? Date.parse(p.criado_em) : 0,
          printedAt: p.impresso_em ? Date.parse(p.impresso_em) : null,
          segmento: p.segmento ?? null,
          segmentoRotulo: p.segmento_rotulo,
          folhas: p.folhas ?? null,
          // Posição na fila da ESCOLA (o servidor calcula sobre todos os
          // pendentes, não só os desta pessoa) e o total, para a tela
          // poder dizer "3º de 27" em vez de um "3º" ambíguo.
          posicaoGlobal: p.posicao_global ?? null,
          totalNaFila: p.total_na_fila ?? null,
          erroMotivo: p.erro_motivo ?? null,
          cancelavel: p.cancelavel === true,
        }));

        setJobs(filaFormatada);
        // Escopo em vigor, resolvido pelo servidor (nunca calculado aqui) —
        // é o que decide o título "Fila — Fundamental I" vs "Fila de
        // Impressão" vs "Minhas Impressões" logo abaixo.
        if (data.escopo) setEscopo(data.escopo as EscopoFila);
      }
    } catch (error) {
      console.error("Erro ao carregar a fila:", error);
    }
  };

  // 2b. ATUALIZAÇÃO AUTOMÁTICA: enquanto a fila está aberta, recarrega a
  // cada 8s para refletir o que o agente de impressão já processou.
  useEffect(() => {
    if (view !== "queue") return;
    const intervalo = setInterval(() => carregarFila(role), 8000);
    return () => clearInterval(intervalo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, role]);

  // 3. ENVIAR DADOS REAIS PARA O BACKEND
  const handleConfirm = async () => {
    // Trava contra clique duplo: se já está enviando, ignora cliques extras.
    if (!draft || isSubmitting) return;
    setIsSubmitting(true);

    const session = getStoredSession();
    if (!session?.token) {
      toast.error("Sua sessão expirou. Entre novamente.");
      handleLogout();
      setIsSubmitting(false);
      return;
    }

    const formData = new FormData();
    // O remetente NÃO é mais enviado pelo cliente: o backend usa o nome
    // que está dentro do token assinado, evitando impressão em nome alheio.
    // "assunto" é usado no envio da Diretoria; "materia"/"turma" no do
    // coordenador. Mandamos os dois — o backend escolhe conforme o cargo
    // (e, para a Diretoria, define a área pelo token, ignorando o resto).
    formData.append("assunto", draft.subject);
    formData.append("materia", draft.subject);
    formData.append("turma", draft.turma);
    formData.append("copias", draft.copies.toString());
    formData.append("cor", draft.color);
    formData.append("frente_verso", draft.pageMode);
    formData.append("acabamento", draft.finishing);
    if (draft.segmento) {
      formData.append("segmento", draft.segmento);
    }

    if (draft.file) {
      formData.append("arquivo", draft.file);
    } else {
      toast.error("É obrigatório anexar um ficheiro PDF.");
      setIsSubmitting(false);
      return; // Interrompe o envio se não houver ficheiro
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/enviar`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.token}` },
        body: formData,
      });

      if (response.status === 401) {
        toast.error("Sua sessão expirou. Entre novamente.");
        handleLogout();
        return;
      }

      const result = await response.json();

      // ENVIO DUPLICADO: o servidor viu o mesmo arquivo há poucos minutos.
      // Perguntamos em vez de mandar de novo em silêncio — é o caso da
      // página que demorou e do segundo clique, que saía em dobro.
      if (response.status === 409 && result.erro === "duplicado") {
        const confirmar = window.confirm(result.mensagem || "Este arquivo já foi enviado há pouco. Enviar mesmo assim?");
        if (!confirmar) {
          setIsSubmitting(false);
          return;
        }
        formData.append("confirmar_duplicado", "1");
        const resposta2 = await fetch(`${API_BASE_URL}/api/enviar`, {
          method: "POST",
          headers: { Authorization: `Bearer ${session.token}` },
          body: formData,
        });
        const result2 = await resposta2.json();
        if (resposta2.ok && result2.status === "sucesso") {
          const base2 = result2.mensagem || "Documento enviado para a fila de impressão com sucesso!";
          toast.success(result2.protocolo ? `${base2} Protocolo ${result2.protocolo}.` : base2);
          setDraft(null);
          setFormResetKey((k) => k + 1);
          setView("queue");
          carregarFila(role);
        } else {
          toast.error(result2.erro || "Não foi possível enviar o documento.");
        }
        setIsSubmitting(false);
        return;
      }

      if (response.ok && result.status === "sucesso") {
        // Mostra a mensagem que o backend mandou (pode avisar sobre o
        // horário de impressão) junto do protocolo, que serve de
        // comprovante do envio para o professor.
        // O total em FOLHAS entra no aviso porque é a unidade em que o
        // erro dói: "32 cópias" não assusta ninguém, "64 folhas" faz a
        // pessoa conferir. É o número real, contado pelo servidor.
        const base = result.mensagem || "Documento enviado para a fila de impressão com sucesso!";
        const detalhes = [
          result.protocolo ? `Protocolo ${result.protocolo}` : null,
          result.folhas ? `${result.folhas} folha${result.folhas === 1 ? "" : "s"} de papel` : null,
        ].filter(Boolean).join(" · ");
        toast.success(detalhes ? `${base} ${detalhes}.` : base);
        setDraft(null);
        setFormResetKey((k) => k + 1);
        setView("queue");
        carregarFila();
      } else {
        toast.error(result.erro || "Ocorreu um erro ao enviar o documento.");
      }
    } catch (error) {
      console.error("Erro de rede:", error);
      toast.error("Erro ao comunicar com o servidor da impressora.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleLogin = (session: Session) => {
    setCurrentUser(session.name);
    setRole(session.role);
    setIsSuperAdmin(session.isSuperAdmin === true);
    setView("dashboard");
    carregarFila(session.role);
  };

  const handleLogout = () => {
    clearSession();
    setCurrentUser("");
    setRole("COORDENADOR");
    setIsSuperAdmin(false);
    setEscopo(null);
    setJobs([]);
    setView("login");
  };

  // Alterna o modo de visualização (Professor / Dep. de T.I.).
  // Só o usuário Admin (isSuperAdmin) pode usar isso a qualquer momento —
  // qualquer outra pessoa é apenas avisada; o papel real dela continua
  // sendo exatamente o que está cadastrado no banco de dados.
  const handleSetRole = (novoRole: Role) => {
    if (!isSuperAdmin) {
      toast.error("Apenas o Administrador pode alternar entre os modos.");
      return;
    }
    // Trocando para um perfil que não enxerga a tela atual: volta para a
    // fila, senão ficaria em branco. Usuários é só do TI; Relatórios é de
    // quem tem acesso a algum tipo (TI, Diretoria ou Coordenação).
    if (view === "admin" && novoRole !== "TI") {
      setView("queue");
    }
    if (view === "report" && !podeVerRelatorios(novoRole)) {
      setView("queue");
    }
    setRole(novoRole);
    carregarFila(novoRole);
  };

  // Funções temporárias da UI
  const cycleStatus = (id: string) => {
    toast.info("A atualização de status será feita pela impressora física.");
  };

  const reprint = (id: string) => {
    toast.info("Reimpressão em desenvolvimento.");
  };

  // CANCELAR: só vale enquanto o pedido está na fila. Quem perde a corrida
  // para o agente recebe 409 e a explicação do servidor — nunca um
  // "cancelado" falso com o papel saindo assim mesmo.
  const cancelarPedido = async (id: string) => {
    const session = getStoredSession();
    if (!session?.token) return;
    if (!window.confirm("Cancelar este pedido? Ele sai da fila e não será impresso.")) return;

    try {
      const resposta = await fetch(`${API_BASE_URL}/api/pedido/${id}/cancelar`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.token}` },
      });
      if (resposta.status === 401) {
        toast.error("Sua sessão expirou. Entre novamente.");
        handleLogout();
        return;
      }
      const dados = await resposta.json().catch(() => ({}));
      if (resposta.ok) {
        toast.success("Pedido cancelado.");
      } else {
        toast.error(dados.erro || "Não foi possível cancelar o pedido.");
      }
      carregarFila(role);
    } catch {
      toast.error("Erro ao comunicar com o servidor.");
    }
  };

  const isAdmin = role === "TI";              // só o TI edita/gerencia
  const ehDiretoria = isDiretoria(role);      // visão global, só leitura
  const podeVerAlgumRelatorio = podeVerRelatorios(role);
  const visibleMetricJobs = jobs; // O backend já filtrou adequadamente por escopo!
  const pendingCount = jobs.filter((j) => j.status === "Pendente").length;

  // Título/subtítulo da fila: reflete o ESCOPO QUE O SERVIDOR CONFIRMOU na
  // última chamada a /api/fila (não um cálculo local) — a coordenadora de
  // segmento precisa saber, sem adivinhar, que não está vendo a escola
  // inteira. Antes da primeira resposta chegar, cai num rótulo neutro.
  const tituloFila =
    escopo?.tipo === "TUDO" ? "Fila de Impressão" :
    escopo?.tipo === "SEGMENTO" ? `Fila — ${escopo.segmento_rotulo ?? rotuloSegmento(escopo.segmento)}` :
    escopo?.tipo === "PROPRIO" ? "Minhas Impressões" :
    "Fila de Impressão";
  const subtituloFila =
    escopo?.tipo === "TUDO" ? "Visão completa de todos os documentos enviados à impressora central." :
    escopo?.tipo === "SEGMENTO" ? `Documentos dos professores do segmento ${escopo.segmento_rotulo ?? rotuloSegmento(escopo.segmento)}.` :
    "Acompanhe o status dos documentos que você enviou.";

  return (
    <div className="min-h-screen bg-[var(--brand-slate)]">
      {view !== "login" && (
        <TopNavbar
          view={view}
          setView={setView}
          role={role}
          setRole={handleSetRole}
          isSuperAdmin={isSuperAdmin}
          currentUser={currentUser}
          segmentoRotulo={escopo?.tipo === "SEGMENTO" ? (escopo.segmento_rotulo ?? rotuloSegmento(escopo.segmento)) : null}
          pendingCount={pendingCount}
          onChangePassword={() => setTrocandoSenha(true)}
          onLogout={handleLogout}
        />
      )}

      <ChangePasswordModal
        open={trocandoSenha}
        onClose={() => setTrocandoSenha(false)}
        onSuccess={(mensagem) => toast.success(mensagem)}
      />

      <main className={`max-w-7xl mx-auto px-6 ${view === "login" ? "py-0" : "py-8"}`}>
        {view === "login" && <LoginScreen onLogin={handleLogin} />}

        {view === "dashboard" && (
          <>
            <div className="mb-6">
              <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a" }}>
                Painel de Solicitações
              </h1>
              <p className="text-slate-500 mt-1">
                Envie documentos para impressão e acompanhe sua fila em tempo real.
              </p>
            </div>

            <div className="grid lg:grid-cols-[1fr_400px] gap-6">
              {ehDiretoria ? (
                <SubmissionFormDiretoria key={formResetKey} role={role} onReview={setDraft} />
              ) : (
                <SubmissionForm key={formResetKey} onReview={setDraft} />
              )}
              <InfoSidebar />
            </div>
          </>
        )}

        {view === "queue" && (
          <div className="space-y-6">
            <div>
              <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a" }}>
                {tituloFila}
              </h1>
              <p className="text-slate-500 mt-1">
                {subtituloFila}
              </p>
            </div>

            <QueueMetricsCards jobs={visibleMetricJobs} />

            <PrintQueueTable
              jobs={jobs} // Passamos a lista direta sem filtros adicionais de front
              role={role}
              currentUser={currentUser}
              mostrarSegmento={escopo?.tipo === "TUDO" || escopo?.tipo === "SEGMENTO"}
              onCycleStatus={cycleStatus}
              onReprint={reprint}
              onCancelar={cancelarPedido}
            />
          </div>
        )}

        {/* Relatórios: TI, Diretoria (leitura) e Coordenação (travada no
            próprio segmento). Gestão de usuários: só TI. O backend reforça
            as regras de forma independente — isto é só pra não renderizar
            uma tela que a rota vai recusar. */}
        {view === "report" && podeVerAlgumRelatorio && <ReportsPanel />}
        {view === "admin" && isAdmin && <AdminUsersPanel />}
      </main>

      <ConfirmationModal
        draft={draft}
        isSubmitting={isSubmitting}
        onCancel={() => setDraft(null)}
        onConfirm={handleConfirm}
      />

      <Toaster position="top-right" richColors />
    </div>
  );
}
