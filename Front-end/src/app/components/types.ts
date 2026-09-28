// ARMADILHA DE NOME: COORDENACAO (coordenadora de segmento — supervisiona)
// é um papel diferente de COORDENADOR (professor comum — já gravado no
// banco, não muda). Nomes parecidos de propósito porque é assim que o
// colégio chama os dois cargos; não é erro de digitação.
export type Role = "COORDENADOR" | "COORDENACAO" | "DIRETOR_ADM" | "DIRETORA_PED" | "TI";

// Cargos da Diretoria (visão global só-leitura). Centralizado aqui para o
// resto do front decidir permissões a partir de um lugar só.
export const PAPEIS_DIRETORIA: Role[] = ["DIRETOR_ADM", "DIRETORA_PED"];
export const isDiretoria = (role: Role) => PAPEIS_DIRETORIA.includes(role);

// -------------------------------------------------------------------------
// SEGMENTOS (coordenações da escola) — espelha banco_dados/__init__.py.
// -------------------------------------------------------------------------
// GERAL não é "mais um segmento de turma": é ao mesmo tempo o escopo de
// quem enxerga a escola inteira (COORDENACAO + segmento GERAL) e o bucket
// dos pedidos do Ensino Médio, porque hoje é a mesma pessoa que acumula os
// dois papéis. O código é ASCII e estável; o rótulo é só apresentação.
export type Segmento = "INFANTIL" | "FUND1" | "FUND2" | "GERAL";
export const SEGMENTOS_VALIDOS: Segmento[] = ["INFANTIL", "FUND1", "FUND2", "GERAL"];
export const ROTULOS_SEGMENTO: Record<Segmento, string> = {
  INFANTIL: "Educação Infantil",
  FUND1: "Fundamental I",
  FUND2: "Fundamental II",
  GERAL: "Geral / Ensino Médio",
};
export function rotuloSegmento(segmento?: string | null): string {
  if (!segmento) return "Não definido";
  return ROTULOS_SEGMENTO[segmento as Segmento] ?? segmento;
}

// Uma CONTA pode participar de mais de um segmento (coordenador de área que
// dá aula no Fund. I e no Fund. II). Estes helpers espelham
// normalizar_segmentos/rotulo_segmentos do backend: lista canônica (ordem de
// SEGMENTOS_VALIDOS, sem repetição) e rótulo juntado ("Fundamental I e
// Fundamental II"). O segmento de um PEDIDO segue sendo UM só.
export function normalizarSegmentos(bruto?: string[] | string | null): Segmento[] {
  const itens = Array.isArray(bruto) ? bruto : (bruto ? bruto.split(",") : []);
  const codigos = new Set(itens.map((s) => s.trim().toUpperCase()).filter(Boolean));
  return SEGMENTOS_VALIDOS.filter((s) => codigos.has(s));
}
export function rotuloSegmentos(segmentos?: string[] | string | null): string {
  const rotulos = normalizarSegmentos(segmentos).map((s) => ROTULOS_SEGMENTO[s]);
  if (rotulos.length === 0) return "Não definido";
  if (rotulos.length === 1) return rotulos[0];
  return `${rotulos.slice(0, -1).join(", ")} e ${rotulos[rotulos.length - 1]}`;
}

// O front NÃO recalcula escopo de visão: quem decide é sempre o servidor
// (/api/fila já vem filtrado e devolve o escopo em vigor; /api/relatorio
// trava o segmento no servidor mesmo que a query string minta). Os antigos
// helpers escopoFrontend/veTudo foram removidos por falta de uso — e já
// estavam errados para contas com mais de um segmento.
// Quem tem acesso a ALGUM relatório — inclui a COORDENACAO de segmento,
// mesmo travada no próprio (o tipo "consumo" já é "por professor").
export const podeVerRelatorios = (role: Role) => role === "TI" || isDiretoria(role) || role === "COORDENACAO";

// Área institucional de cada cargo da Diretoria (espelha o backend).
export const AREA_DO_CARGO: Partial<Record<Role, string>> = {
  DIRETOR_ADM: "Administrativa",
  DIRETORA_PED: "Pedagógica",
};

// -------------------------------------------------------------------------
// TURMAS E MATÉRIAS
// -------------------------------------------------------------------------
// Espelho de `TURMAS_VALIDAS` / `MATERIAS_VALIDAS` em banco_dados/__init__.py.
// Mexeu aqui, mexa lá também: quem recusa o envio é o servidor, então uma
// turma que só exista neste arquivo aparece na tela e depois dá erro 400.
//
// O que vai para o banco é o nome da turma ("7º Ano"), não o grupo. O
// `codigo` é o segmento correspondente ao grupo (Ensino Médio cai no bucket
// GERAL — ver o comentário em Segmento): o formulário usa isso para
// pré-preencher o campo Segmento a partir da turma marcada.
export const TURMAS_POR_SEGMENTO: { segmento: string; codigo: Segmento; turmas: string[] }[] = [
  { segmento: "Educação Infantil", codigo: "INFANTIL", turmas: ["Maternal 1", "Maternal 2", "Jardim 1", "Jardim 2"] },
  { segmento: "Ensino Fundamental I", codigo: "FUND1", turmas: ["1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"] },
  { segmento: "Ensino Fundamental II", codigo: "FUND2", turmas: ["6º Ano", "7º Ano", "8º Ano", "9º Ano"] },
  { segmento: "Ensino Médio", codigo: "GERAL", turmas: ["1º EM", "2º EM", "3º EM"] },
];
// Segmento correspondente a uma turma marcada, ou "" se a turma não estiver
// em nenhum grupo (não deveria acontecer — as caixas vêm da lista acima).
export function segmentoDaTurma(turma: string): Segmento | "" {
  return TURMAS_POR_SEGMENTO.find((g) => g.turmas.includes(turma))?.codigo ?? "";
}

// Em ordem alfabética.
export const MATERIAS: string[] = [
  "Biologia",
  "Ciências",
  "Filosofia",
  "Física",
  "Geografia",
  "História",
  "Inglês",
  "Matemática",
  "Português",
  "Química",
  "Sociologia",
];

// Marcar "Outro" abre um campo de texto — é para o que não é matéria regular
// (capa de avaliação, simulado, recuperação). O rótulo NÃO é gravado: o que
// vai para o banco é o texto digitado.
export const MATERIA_OUTRO = "Outro";
export const MATERIA_OUTRO_MAX = 60;

// Mesmo arranjo para a turma: nem toda impressão pertence a uma turma
// (material de uso próprio do professor, reunião de pais, formação).
// Espelha normalizar_turma em banco_dados/__init__.py.
export const TURMA_OUTRO = "Outro";
export const TURMA_OUTRO_MAX = 60;

// Tamanho mínimo de senha — espelha ACALANTO_SENHA_MINIMA no servidor
// (que é quem de fato recusa). 4 caracteres somados a um login sem limite
// de tentativas era força bruta em segundos.
export const SENHA_MINIMA = 8;

// Papel A3 NÃO passa pelo sistema (decisão da gestão em ago/2026): A3 é
// impressão especial, tratada direto com o T.I. Tudo sai no padrão da
// fila (A4).

export type JobStatus = "Pendente" | "Imprimindo" | "Concluído" | "Erro" | "Cancelado";

// O que o professor lê. Os valores acima são os do banco, usados em
// relatórios, na cota e na purga de PDFs — renomeá-los exigiria migração.
//
// "Concluído" aparece como "Enviado à impressora" porque é só isso que o
// sistema sabe: o agente entrega o trabalho ao servidor de impressão e
// confere se não travou na fila. O que acontece dentro do equipamento —
// papel acabando no meio, o painel recusando por cota de departamento —
// está fora do alcance dele.
export const STATUS_LABELS: Record<JobStatus, string> = {
  Pendente: "Na fila",
  Imprimindo: "Saindo na impressora",
  Concluído: "Enviado à impressora",
  Erro: "Erro",
  Cancelado: "Cancelado",
};
export type ColorMode = "PB" | "Colorida";
export type PageMode = "Frente" | "FrenteVerso";
export type Finishing = "Normal" | "Grampeada";

export type PrintJob = {
  id: string;
  sender: string;
  subject: string;
  turma: string;
  fileName: string;
  copies: number;
  pages?: number | null;
  color: ColorMode;
  pageMode: PageMode;
  finishing: Finishing;
  status: JobStatus;
  submittedAt: number;
  printedAt?: number | null;
  segmento?: string | null;
  segmentoRotulo?: string;
  // FOLHAS DE PAPEL do pedido (páginas ÷ 2 em frente e verso, × cópias).
  // Unidade diferente de "impressões", que conta faces.
  folhas?: number | null;
  // Posição na fila da ESCOLA (não só entre os pedidos de quem olha) e o
  // total de pendentes — juntos permitem escrever "3º de 27".
  posicaoGlobal?: number | null;
  totalNaFila?: number | null;
  // Motivo do erro, em português, vindo do agente.
  erroMotivo?: string | null;
  // O servidor já diz se ESTA pessoa pode cancelar ESTE pedido (dono +
  // ainda na fila) — o botão não precisa recalcular a regra.
  cancelavel?: boolean;
};

export const ROLE_LABELS: Record<Role, string> = {
  COORDENADOR: "COORDENADOR DE ÁREA",
  COORDENACAO: "COORDENAÇÃO DE SEGMENTO",
  DIRETOR_ADM: "DIRETOR ADMINISTRATIVO",
  DIRETORA_PED: "DIRETORA PEDAGÓGICA",
  TI: "DEP. DE T.I.",
};

// Rótulo curto usado ao lado do nome do usuário no topo.
export const ROLE_PESSOA_LABEL: Record<Role, string> = {
  COORDENADOR: "Professor",
  COORDENACAO: "Coordenação de Segmento",
  DIRETOR_ADM: "Diretor Administrativo",
  DIRETORA_PED: "Diretora Pedagógica",
  TI: "Dep. de TI",
};

export const COLOR_LABELS: Record<ColorMode, string> = {
  PB: "P/B (Preto e Branco)",
  Colorida: "Colorida",
};

export const PAGE_MODE_LABELS: Record<PageMode, string> = {
  Frente: "Apenas Frente",
  FrenteVerso: "Frente e Verso",
};
