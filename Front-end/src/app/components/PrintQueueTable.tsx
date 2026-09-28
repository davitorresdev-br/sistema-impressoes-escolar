import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { IdlePrinterIllustration } from "./IdlePrinterIllustration";
import { JobStatus, PrintJob, Role, STATUS_LABELS } from "./types";
import { ArrowRight, FileText, RotateCcw, XCircle } from "lucide-react";

type Props = {
  jobs: PrintJob[];
  role: Role;
  currentUser: string;
  // Só faz sentido mostrar de quem é o segmento quando a tela já mostra
  // gente de mais de um lugar (escopo TUDO ou SEGMENTO) — pra um professor
  // vendo só os próprios pedidos, a coluna seria ruído.
  mostrarSegmento?: boolean;
  onCycleStatus: (id: string) => void;
  onReprint: (id: string) => void;
  onCancelar?: (id: string) => void;
};

const STATUS_STYLES: Record<JobStatus, string> = {
  Pendente: "bg-amber-100 text-amber-800 border-amber-200",
  Imprimindo: "bg-blue-100 text-blue-800 border-blue-200",
  Concluído: "bg-emerald-100 text-emerald-800 border-emerald-200",
  Erro: "bg-red-100 text-red-800 border-red-200",
  Cancelado: "bg-slate-100 text-slate-600 border-slate-300",
};

function formatarData(ms?: number): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

/** Explica a conta das folhas, para quem passa o mouse.
 *
 * O arredondamento é POR DOCUMENTO: em frente e verso, 5 páginas ocupam 3
 * folhas (a terceira sai com o verso em branco), não 2,5 — não existe
 * imprimir meia folha. Por isso 5 páginas × 12 cópias dá 36 folhas, e não
 * os 60÷2 = 30 que o cálculo intuitivo sugere. Com número PAR de páginas
 * as duas contas coincidem, o que faz a diferença parecer erro. */
function explicarFolhas(job: PrintJob): string {
  if (!job.folhas || !job.pages) return "";
  if (job.pageMode !== "FrenteVerso") {
    return `${job.pages} páginas × ${job.copies} cópias = ${job.folhas} folhas.`;
  }
  const porCopia = Math.ceil(job.pages / 2);
  const sobra = job.pages % 2 === 1
    ? " (a última folha sai com o verso em branco)"
    : "";
  return `Frente e verso: ${job.pages} páginas ocupam ${porCopia} folhas por cópia${sobra}` +
    ` × ${job.copies} cópias = ${job.folhas} folhas.`;
}

function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <Badge
      variant="outline"
      // whitespace-normal + h-auto vencem o nowrap/overflow-hidden do kit
      // (twMerge fica com a última classe): "Enviado à impressora" pode
      // quebrar em duas linhas DENTRO do badge, em vez de alargar a tabela
      // até a coluna sair da tela — era essa a causa do texto "cortado".
      className={`${STATUS_STYLES[status]} whitespace-normal h-auto text-center leading-tight max-w-[9.5rem]`}
      title={
        status === "Concluído"
          ? "O documento foi entregue à impressora e não travou na fila. Se não estiver na bandeja, verifique papel, toner e o painel do equipamento."
          : undefined
      }
    >
      {status === "Imprimindo" && (
        <span className="relative flex h-1.5 w-1.5 mr-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-500 opacity-75" />
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-blue-600" />
        </span>
      )}
      {STATUS_LABELS[status]}
    </Badge>
  );
}

export function PrintQueueTable({ jobs, role, currentUser, mostrarSegmento, onCycleStatus, onReprint, onCancelar }: Props) {
  // Coordenador vê só os próprios envios; TI e Diretoria veem todos. Mas
  // apenas o TI EDITA (avançar status / reimprimir) — a Diretoria é leitura.
  const isTeacher = role === "COORDENADOR";
  const canEdit = role === "TI";
  const visibleJobs = isTeacher ? jobs.filter((j) => j.sender === currentUser) : jobs;

  // A POSIÇÃO VEM DO SERVIDOR e é a da fila da ESCOLA. Calcular aqui, sobre
  // a lista que a pessoa recebeu, diria "1º" para o primeiro pedido DELA
  // mesmo havendo 30 na frente — o sistema prometendo o que não cumpre.
  const posicaoNaFila = (job: PrintJob): string => {
    if (job.status === "Imprimindo") return "Saindo agora";
    if (job.status !== "Pendente") return "—";
    if (!job.posicaoGlobal) return "—";
    // "3º de 27" é honesto e informativo; "3º" sozinho é ambíguo.
    return job.totalNaFila ? `${job.posicaoGlobal}º de ${job.totalNaFila}` : `${job.posicaoGlobal}º`;
  };

  if (visibleJobs.length === 0) {
    return (
      <Card className="p-12 flex flex-col items-center justify-center text-center border-[var(--brand-border)]">
        <IdlePrinterIllustration />
        <p className="mt-6 text-slate-700" style={{ fontSize: "1.125rem", fontWeight: 600 }}>
          Nenhuma impressão pendente na fila.
        </p>
        <p className="text-slate-500 mt-1">Quando você enviar um documento, ele aparecerá aqui.</p>
      </Card>
    );
  }

  return (
    <Card className="border-[var(--brand-border)] overflow-hidden">
      <div className="px-6 py-4 border-b border-[var(--brand-border)] flex items-center justify-between">
        <div>
          <p style={{ fontWeight: 600, color: "#0f172a" }}>
            {isTeacher ? "Minhas Impressões" : "Fila Completa de Impressão"}
          </p>
          <p className="text-slate-500" style={{ fontSize: "0.85rem" }}>
            {isTeacher
              ? "Apenas os documentos enviados por você são exibidos."
              : "Todos os documentos enviados pelos coordenadores de área."}
          </p>
        </div>
        <Badge variant="outline" className="bg-slate-50">
          {visibleJobs.length} {visibleJobs.length === 1 ? "registro" : "registros"}
        </Badge>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50">
              <TableHead>ID</TableHead>
              {!isTeacher && <TableHead>Remetente</TableHead>}
              {mostrarSegmento && <TableHead>Segmento</TableHead>}
              <TableHead>Matéria / Turma</TableHead>
              <TableHead>Arquivo</TableHead>
              <TableHead className="text-center">Cópias</TableHead>
              <TableHead>{isTeacher ? "Sua Posição na Fila" : "Fila"}</TableHead>
              <TableHead>Enviado em</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visibleJobs.map((job) => (
              <TableRow key={job.id} className="hover:bg-slate-50/50">
                <TableCell className="text-slate-500" style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.8rem" }}>
                  {job.id}
                </TableCell>
                {!isTeacher && (
                  <TableCell style={{ fontWeight: 500 }}>{job.sender}</TableCell>
                )}
                {mostrarSegmento && (
                  <TableCell>
                    <Badge variant="outline" className="bg-slate-50 text-slate-600 border-slate-200" style={{ fontSize: "0.75rem" }}>
                      {job.segmentoRotulo || "Não definido"}
                    </Badge>
                  </TableCell>
                )}
                <TableCell>
                  <div style={{ fontWeight: 500, color: "#0f172a" }}>{job.subject}</div>
                  <div className="text-slate-500" style={{ fontSize: "0.8rem" }}>{job.turma}</div>
                </TableCell>
                <TableCell>
                  {/* Só o nome, sem cara de link: não existe rota para o
                      usuário baixar o PDF por aqui, e um botão que não faz
                      nada ensina a desconfiar dos botões que fazem. */}
                  <span className="inline-flex items-center gap-1.5 text-slate-600" style={{ fontSize: "0.85rem" }}>
                    <FileText size={14} className="shrink-0 text-slate-400" />
                    <span className="max-w-[180px] truncate">{job.fileName}</span>
                  </span>
                </TableCell>
                <TableCell className="text-center">
                  {job.copies}
                  {job.pages ? <span className="text-slate-400"> × {job.pages}p</span> : null}
                  {/* Folhas de PAPEL, com o MODO ao lado. Sem o modo, "5
                      páginas × 12 cópias = 36 folhas" parece conta errada
                      (o intuitivo é 60). O title explica o arredondamento
                      por documento: em frente e verso, 5 páginas ocupam 3
                      folhas — a última sai com o verso em branco. */}
                  {job.folhas ? (
                    <div className="text-slate-500" style={{ fontSize: "0.75rem" }} title={explicarFolhas(job)}>
                      {job.folhas} folha{job.folhas === 1 ? "" : "s"}
                      {job.pageMode === "FrenteVerso" ? " · frente e verso" : ""}
                    </div>
                  ) : null}
                </TableCell>
                <TableCell>
                  {isTeacher ? (
                    <Badge className="bg-[var(--brand-blue)] text-white hover:bg-[var(--brand-blue)] whitespace-nowrap">
                      {posicaoNaFila(job)}
                    </Badge>
                  ) : (
                    <span className="text-slate-600 whitespace-nowrap">{posicaoNaFila(job)}</span>
                  )}
                </TableCell>
                <TableCell className="text-slate-600" style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                  {formatarData(job.submittedAt)}
                  {job.printedAt ? (
                    <div className="text-emerald-600" style={{ fontSize: "0.7rem" }}>
                      Impresso {formatarData(job.printedAt)}
                    </div>
                  ) : null}
                </TableCell>
                <TableCell>
                  <StatusBadge status={job.status} />
                  {/* O motivo do erro, em português, do lado do status: sem
                      ele o professor não sabe se reenvia, espera ou liga. */}
                  {job.status === "Erro" && job.erroMotivo && (
                    <div className="text-red-700 mt-1 max-w-[16rem]" style={{ fontSize: "0.75rem", lineHeight: 1.3 }}>
                      {job.erroMotivo}
                    </div>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    {/* Quem pode cancelar é decidido pelo SERVIDOR (dono do
                        pedido + ainda na fila) — a tela só obedece. */}
                    {job.cancelavel && onCancelar && (
                      <Button size="sm" variant="ghost" onClick={() => onCancelar(job.id)}
                              className="gap-1 text-[var(--brand-red)]">
                        <XCircle size={14} /> Cancelar
                      </Button>
                    )}
                    {canEdit && (job.status !== "Concluído" ? (
                      <Button size="sm" variant="outline" onClick={() => onCycleStatus(job.id)} className="gap-1">
                        Avançar <ArrowRight size={14} />
                      </Button>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => onReprint(job.id)} className="gap-1 text-[var(--brand-blue)]">
                        <RotateCcw size={14} /> Reimprimir
                      </Button>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}
