import { useEffect, useMemo, useState } from "react";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Badge } from "./ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { Download, ExternalLink, FileBarChart } from "lucide-react";
import { toast } from "sonner";
import { Role, SEGMENTOS_VALIDOS, ROTULOS_SEGMENTO, rotuloSegmento } from "./types";
import { getStoredSession, clearSession } from "./LoginScreen";
import { API_BASE_URL } from "../config";

type Tipo = "consumo" | "custos" | "materias";

const TIPO_LABEL: Record<Tipo, string> = {
  consumo: "Por professor",
  custos: "Custos (P&B × Colorida)",
  materias: "Por matéria",
};

const TIPO_DESCRICAO: Record<Tipo, string> = {
  consumo: "Total de impressões (páginas × cópias) por professor.",
  custos: "Cópias e impressões separadas em Preto-e-Branco × Colorida, para levantamento de custo.",
  materias: "Documentos enviados pelos docentes, agrupados por matéria.",
};

// Sentinelas pro <Select>, que não aceita "" como valor de item.
const TODOS_PROFESSORES = "__TODOS__";
const TODOS_SEGMENTOS = "__TODOS__";
// Acima deste número de nomes, o dropdown vira um campo com busca (datalist
// nativo) — um <select> de 40 professores é inutilizável.
const LIMITE_SELECT_PROFESSOR = 15;

function tiposDoCargo(role?: Role): Tipo[] {
  if (role === "TI") return ["consumo", "custos", "materias"];
  if (role === "DIRETOR_ADM") return ["custos"];
  if (role === "DIRETORA_PED") return ["materias"];
  // Coordenação de segmento: só "consumo" (por professor) já é o tipo que
  // faz sentido travado no próprio segmento.
  if (role === "COORDENACAO") return ["consumo"];
  return [];
}

function formatarData(iso?: string): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  return new Date(ms).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function MetricCard({ label, value, sub, cor }: { label: string; value: number; sub: string; cor: string }) {
  return (
    <Card className="p-6 bg-white shadow-sm" style={{ borderLeft: `4px solid ${cor}` }}>
      <p className="text-slate-500" style={{ fontSize: "0.85rem", fontWeight: 600, letterSpacing: "0.05em" }}>{label}</p>
      <p className="mt-2" style={{ fontSize: "2.25rem", fontWeight: 700, color: "#0f172a", lineHeight: 1 }}>{value}</p>
      <p className="text-slate-500 mt-1" style={{ fontSize: "0.8rem" }}>{sub}</p>
    </Card>
  );
}

// Texto do estado vazio, explícito sobre QUAL filtro não achou nada — uma
// tabela em branco não diz se é "sem pedido no período" ou "esse professor
// não existe"/"segmento errado".
function textoVazio(professor?: string, segmentoRotulo?: string): string {
  if (professor && segmentoRotulo) return `Nenhuma impressão de ${professor} em ${segmentoRotulo} no período.`;
  if (professor) return `Nenhuma impressão de ${professor} no período.`;
  if (segmentoRotulo) return `Nenhuma impressão em ${segmentoRotulo} no período.`;
  return "Nenhum pedido no período.";
}

export function ReportsPanel() {
  const role = getStoredSession()?.role as Role | undefined;
  const tipos = useMemo(() => tiposDoCargo(role), [role]);

  const [tipo, setTipo] = useState<Tipo>(tipos[0] ?? "consumo");
  const [inicio, setInicio] = useState("");
  const [fim, setFim] = useState("");
  const [professor, setProfessor] = useState("");
  const [segmentoFiltro, setSegmentoFiltro] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  // Trava vinda do SERVIDOR (nunca calculada aqui): quando uma Coordenação
  // de segmento carrega o relatório, o segmento já vem travado na resposta
  // — o campo fica desabilitado mostrando o recorte real, e pedir outro
  // segmento na query não teria efeito nenhum (o backend ignora). O recorte
  // pode cobrir MAIS DE UM segmento (conta com vários cadastrados) — daí
  // 'segmentos' + 'segmento_rotulo' já juntado; 'segmento' único só vem
  // preenchido quando o recorte é de um segmento só.
  const filtrosServidor = data?.filtros as {
    professor: string | null;
    segmento: string | null;
    segmentos?: string[];
    segmento_rotulo?: string | null;
    segmento_travado: boolean;
  } | undefined;
  const segmentoTravado = filtrosServidor?.segmento_travado === true;
  const professoresDisponiveis: string[] = data?.professores_disponiveis ?? [];

  const queryString = (extra: Record<string, string> = {}) => {
    const params = new URLSearchParams({ tipo, ...extra });
    if (inicio) params.set("data_inicio", inicio);
    if (fim) params.set("data_fim", fim);
    if (professor) params.set("professor", professor);
    if (segmentoFiltro) params.set("segmento", segmentoFiltro);
    return params.toString();
  };

  const carregar = async () => {
    const session = getStoredSession();
    if (!session?.token) return;
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE_URL}/api/relatorio?${queryString()}`, {
        headers: { Authorization: `Bearer ${session.token}` },
      });
      if (resp.status === 401) {
        // 401 = sessão expirada (ou derrubada por troca de senha): explicar
        // e voltar ao login. Só 401 desloga — um 403 (sessão boa, cargo sem
        // acesso) expulsava do sistema quem só precisava ler "sem
        // permissão", e o servidor agora distingue os dois.
        toast.error("Sua sessão expirou. Entre novamente.");
        clearSession();
        window.location.reload();
        return;
      }
      if (resp.status === 403) {
        const dados = await resp.json().catch(() => ({}));
        toast.error(dados.erro || "Seu cargo não tem acesso a este relatório.");
        return;
      }
      if (!resp.ok) { toast.error("Não foi possível carregar o relatório."); return; }
      const json = await resp.json();
      // Marca a resposta com o tipo que a gerou. Assim só renderizamos o
      // corpo certo quando os dados batem com a aba — evita renderizar,
      // por ex., o relatório "por matéria" com dados de "por professor"
      // (o que quebrava a tela ao trocar de aba).
      setData({ ...json, _tipo: tipo });
      // Reflete o que o servidor de fato aplicou — se travado, o select
      // mostra o segmento real da coordenadora, não o que estava digitado.
      if (json.filtros?.segmento_travado) setSegmentoFiltro(json.filtros.segmento ?? "");
    } catch {
      toast.error("Erro ao comunicar com o servidor.");
    } finally {
      setLoading(false);
    }
  };

  // Recarrega ao abrir e sempre que o tipo (aba) muda. Professor/segmento
  // exigem clicar em "Aplicar filtros" — o professor pode ser um campo de
  // texto livre (busca), e recarregar a cada tecla digitada sobrecarregaria
  // o servidor à toa.
  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tipo]);

  const baixarCSV = async () => {
    const session = getStoredSession();
    if (!session?.token) return;
    try {
      const resp = await fetch(`${API_BASE_URL}/api/relatorio?${queryString({ formato: "csv" })}`, {
        headers: { Authorization: `Bearer ${session.token}` },
      });
      if (!resp.ok) { toast.error("Não foi possível gerar o CSV."); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      // O nome do arquivo vem do servidor (já inclui professor/segmento
      // filtrados, sanitizados) — blob: URLs não carregam o cabeçalho
      // Content-Disposition sozinhas, então precisamos ler e repassar aqui.
      const disposicao = resp.headers.get("Content-Disposition") || "";
      const nomeServidor = /filename="?([^"]+)"?/.exec(disposicao)?.[1];
      a.download = nomeServidor || `relatorio_${tipo}_${inicio || "inicio"}_a_${fim || "hoje"}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Erro ao baixar o CSV.");
    }
  };

  const abrirDocumento = async (id: number) => {
    const session = getStoredSession();
    if (!session?.token) return;

    // Abrimos a aba AGORA, ainda dentro do clique — senão o navegador
    // bloqueia o pop-up (a abertura aconteceria depois do await do fetch).
    // O PDF precisa do token no cabeçalho, então baixamos por fetch e só
    // depois apontamos a aba já aberta para o conteúdo.
    const aba = window.open("", "_blank");
    try {
      const resp = await fetch(`${API_BASE_URL}/api/relatorio/documento/${id}`, {
        headers: { Authorization: `Bearer ${session.token}` },
      });
      if (!resp.ok) {
        aba?.close();
        toast.error(resp.status === 410
          ? "Documento expirado pela política de retenção."
          : "Não foi possível abrir o documento.");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      if (aba) {
        aba.location.href = url;
      } else {
        // Pop-up bloqueado: baixa o arquivo como alternativa.
        const a = document.createElement("a");
        a.href = url;
        a.download = `documento_${id}.pdf`;
        a.click();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      aba?.close();
      toast.error("Erro ao abrir o documento.");
    }
  };

  const rotuloFiltroAtual = segmentoTravado
    ? (filtrosServidor?.segmento_rotulo ?? rotuloSegmento(filtrosServidor?.segmento))
    : (segmentoFiltro ? rotuloSegmento(segmentoFiltro) : undefined);

  return (
    <div className="space-y-6">
      <div>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a" }}>Relatórios</h1>
        <p className="text-slate-500 mt-1">{TIPO_DESCRICAO[tipo]}</p>
      </div>

      {/* Abas só aparecem para quem tem mais de um relatório (TI). */}
      {tipos.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {tipos.map((t) => (
            <button
              key={t}
              onClick={() => setTipo(t)}
              className={`px-4 h-9 rounded-md text-sm border transition ${
                tipo === t
                  ? "bg-[var(--brand-blue)] text-white border-[var(--brand-blue)]"
                  : "bg-white text-slate-700 border-[var(--brand-border)] hover:bg-slate-50"
              }`}
            >
              {TIPO_LABEL[t]}
            </button>
          ))}
        </div>
      )}

      <Card className="p-6 border-[var(--brand-border)] shadow-sm">
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-2">
            <Label htmlFor="inicio">De</Label>
            <Input id="inicio" type="date" value={inicio} onChange={(e) => setInicio(e.target.value)} className="w-44" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="fim">Até</Label>
            <Input id="fim" type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-44" />
          </div>

          {professoresDisponiveis.length > LIMITE_SELECT_PROFESSOR ? (
            <div className="space-y-2">
              <Label htmlFor="professor-busca">Professor</Label>
              <Input
                id="professor-busca"
                list="professores-disponiveis"
                value={professor}
                onChange={(e) => setProfessor(e.target.value)}
                placeholder="Todos"
                className="w-56"
              />
              <datalist id="professores-disponiveis">
                {professoresDisponiveis.map((p) => <option key={p} value={p} />)}
              </datalist>
            </div>
          ) : (
            <div className="space-y-2">
              <Label>Professor</Label>
              <Select value={professor || TODOS_PROFESSORES} onValueChange={(v) => setProfessor(v === TODOS_PROFESSORES ? "" : v)}>
                <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={TODOS_PROFESSORES}>Todos</SelectItem>
                  {professoresDisponiveis.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <Label>Segmento</Label>
            {segmentoTravado ? (
              // Travado pelo servidor: mostra o recorte real, que pode
              // cobrir mais de um segmento — um <Select> de valor único
              // não representaria "Fundamental I e Fundamental II".
              <Input
                disabled
                value={filtrosServidor?.segmento_rotulo ?? rotuloSegmento(filtrosServidor?.segmento)}
                className="w-56"
              />
            ) : (
              <Select
                value={segmentoFiltro || TODOS_SEGMENTOS}
                onValueChange={(v) => setSegmentoFiltro(v === TODOS_SEGMENTOS ? "" : v)}
              >
                <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={TODOS_SEGMENTOS}>Todos os segmentos</SelectItem>
                  {SEGMENTOS_VALIDOS.map((s) => <SelectItem key={s} value={s}>{ROTULOS_SEGMENTO[s]}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
            {segmentoTravado && (
              <p className="text-slate-400" style={{ fontSize: "0.75rem" }}>
                {(filtrosServidor?.segmentos?.length ?? 0) > 1 ? "Travado nos seus segmentos." : "Travado no seu segmento."}
              </p>
            )}
          </div>

          <Button onClick={carregar} disabled={loading} className="bg-[var(--brand-blue)] hover:bg-[var(--brand-blue-hover)] text-white h-10">
            <FileBarChart size={16} className="mr-2" />
            {loading ? "Carregando..." : "Aplicar filtros"}
          </Button>
          <Button onClick={baixarCSV} variant="outline" className="h-10">
            <Download size={16} className="mr-2" />
            Baixar CSV
          </Button>
        </div>
      </Card>

      {data?._tipo === "consumo" && <ConsumoBody data={data} textoVazioMsg={textoVazio(filtrosServidor?.professor ?? undefined, rotuloFiltroAtual)} />}
      {data?._tipo === "custos" && <CustosBody data={data} textoVazioMsg={textoVazio(filtrosServidor?.professor ?? undefined, rotuloFiltroAtual)} />}
      {data?._tipo === "materias" && <MateriasBody data={data} onAbrir={abrirDocumento} textoVazioMsg={textoVazio(filtrosServidor?.professor ?? undefined, rotuloFiltroAtual)} />}
    </div>
  );
}

function ConsumoBody({ data, textoVazioMsg }: { data: any; textoVazioMsg: string }) {
  const linhas: any[] = data.linhas ?? [];
  const totais = data.totais ?? { impressoes: 0, copias: 0, pedidos: 0 };
  return (
    <>
      {/* DUAS UNIDADES, de propósito: "impressões" conta faces (é o que o
          toner gasta e o que o contrato da Konica cobra por clique) e
          "folhas" conta papel (o que a escola compra). Trocar uma pela
          outra em silêncio faria o número acompanhado há meses cair pela
          metade sem explicação. */}
      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
        <MetricCard label="FOLHAS DE PAPEL" value={totais.folhas ?? 0} sub="papel consumido no período" cor="var(--brand-blue)" />
        <MetricCard label="IMPRESSÕES" value={totais.impressoes} sub="faces impressas (páginas × cópias)" cor="#6366f1" />
        <MetricCard label="CÓPIAS" value={totais.copias} sub="jogos solicitados" cor="var(--brand-amber)" />
        <MetricCard label="PEDIDOS" value={totais.pedidos} sub="documentos enviados" cor="#10b981" />
      </div>
      <Card className="border-[var(--brand-border)] overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Professor</TableHead>
                <TableHead>Identificador</TableHead>
                <TableHead className="text-center">Pedidos</TableHead>
                <TableHead className="text-center">Cópias</TableHead>
                <TableHead className="text-center">Páginas</TableHead>
                <TableHead className="text-center">Folhas (papel)</TableHead>
                <TableHead className="text-center">Impressões (faces)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {linhas.length === 0 ? (
                <TableRow><TableCell colSpan={7} className="text-center text-slate-500 py-8">{textoVazioMsg}</TableCell></TableRow>
              ) : linhas.map((l: any) => (
                <TableRow key={l.usuario_uid || l.professor_nome} className="hover:bg-slate-50/50">
                  <TableCell style={{ fontWeight: 500 }}>{l.professor_nome}</TableCell>
                  <TableCell className="text-slate-500" style={{ fontSize: "0.8rem" }}>{l.usuario_uid || "—"}</TableCell>
                  <TableCell className="text-center">{l.pedidos}</TableCell>
                  <TableCell className="text-center">{l.total_copias}</TableCell>
                  <TableCell className="text-center">{l.total_paginas}</TableCell>
                  <TableCell className="text-center" style={{ fontWeight: 600 }}>{l.total_folhas ?? "—"}</TableCell>
                  <TableCell className="text-center">{l.total_impressoes}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>
    </>
  );
}

function CustosBody({ data, textoVazioMsg }: { data: any; textoVazioMsg: string }) {
  const porCor: any[] = data.por_cor ?? [];
  const porProfessor: any[] = data.por_professor ?? [];
  const pb = porCor.find((c: any) => c.categoria === "Preto e Branco");
  const cor = porCor.find((c: any) => c.categoria === "Colorida");
  const totalImpr = (pb?.impressoes || 0) + (cor?.impressoes || 0);

  return (
    <>
      <div className="grid md:grid-cols-3 gap-5">
        <MetricCard label="TOTAL DE IMPRESSÕES" value={totalImpr} sub="páginas × cópias no período" cor="var(--brand-blue)" />
        <MetricCard label="PRETO E BRANCO" value={pb?.impressoes || 0} sub={`${pb?.copias || 0} cópias`} cor="#475569" />
        <MetricCard label="COLORIDA" value={cor?.impressoes || 0} sub={`${cor?.copias || 0} cópias`} cor="#e11d48" />
      </div>
      <Card className="border-[var(--brand-border)] overflow-hidden">
        <div className="px-6 py-3 border-b border-[var(--brand-border)]">
          <p style={{ fontWeight: 600, color: "#0f172a" }}>Consumo por professor</p>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Professor</TableHead>
                <TableHead className="text-center">Cópias P&B</TableHead>
                <TableHead className="text-center">Cópias Colorida</TableHead>
                <TableHead className="text-center">Impr. P&B</TableHead>
                <TableHead className="text-center">Impr. Colorida</TableHead>
                <TableHead className="text-center">Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {porProfessor.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center text-slate-500 py-8">{textoVazioMsg}</TableCell></TableRow>
              ) : porProfessor.map((p: any) => (
                <TableRow key={p.professor_nome} className="hover:bg-slate-50/50">
                  <TableCell style={{ fontWeight: 500 }}>{p.professor_nome}</TableCell>
                  <TableCell className="text-center">{p.copias_pb}</TableCell>
                  <TableCell className="text-center">{p.copias_cor}</TableCell>
                  <TableCell className="text-center">{p.impressoes_pb}</TableCell>
                  <TableCell className="text-center">{p.impressoes_cor}</TableCell>
                  <TableCell className="text-center" style={{ fontWeight: 600 }}>{p.impressoes_pb + p.impressoes_cor}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>
    </>
  );
}

function MateriasBody({ data, onAbrir, textoVazioMsg }: { data: any; onAbrir: (id: number) => void; textoVazioMsg: string }) {
  const documentos: any[] = data.documentos ?? [];
  const totais = data.totais ?? { documentos: 0, impressoes: 0 };
  // Agrupa os documentos por matéria.
  const grupos: Record<string, any[]> = {};
  for (const d of documentos) {
    (grupos[d.materia] ||= []).push(d);
  }
  const materias = Object.keys(grupos);

  return (
    <>
      <div className="grid md:grid-cols-2 gap-5">
        <MetricCard label="DOCUMENTOS" value={totais.documentos} sub="enviados pelos docentes" cor="var(--brand-blue)" />
        <MetricCard label="IMPRESSÕES" value={totais.impressoes} sub="páginas × cópias no período" cor="#10b981" />
      </div>

      {materias.length === 0 ? (
        <Card className="p-10 text-center text-slate-500 border-[var(--brand-border)]">{textoVazioMsg}</Card>
      ) : materias.map((materia) => (
        <Card key={materia} className="border-[var(--brand-border)] overflow-hidden">
          <div className="px-6 py-3 border-b border-[var(--brand-border)] flex items-center justify-between bg-slate-50">
            <p style={{ fontWeight: 600, color: "#0f172a" }}>{materia}</p>
            <Badge variant="outline" className="bg-white">{grupos[materia].length} doc(s)</Badge>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Documento</TableHead>
                  <TableHead>Docente</TableHead>
                  <TableHead className="text-center">Cópias</TableHead>
                  <TableHead>Enviado em</TableHead>
                  <TableHead className="text-right">Conteúdo</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {grupos[materia].map((d: any) => (
                  <TableRow key={d.id} className="hover:bg-slate-50/50">
                    <TableCell>
                      <span className="max-w-[240px] truncate inline-block align-bottom" style={{ fontWeight: 500 }}>{d.arquivo_nome}</span>
                      {d.paginas ? <span className="text-slate-400"> · {d.paginas}p</span> : null}
                    </TableCell>
                    <TableCell className="text-slate-700">{d.professor_nome}</TableCell>
                    <TableCell className="text-center">{d.copias}</TableCell>
                    <TableCell className="text-slate-600" style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>{formatarData(d.criado_em)}</TableCell>
                    <TableCell className="text-right">
                      {d.arquivo_purgado ? (
                        <span className="text-slate-400" style={{ fontSize: "0.8rem" }}>expirado</span>
                      ) : (
                        <Button size="sm" variant="outline" onClick={() => onAbrir(d.id)} className="gap-1">
                          <ExternalLink size={14} /> Abrir
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      ))}
    </>
  );
}
