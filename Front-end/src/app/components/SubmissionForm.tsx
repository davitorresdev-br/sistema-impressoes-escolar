import { useMemo, useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Card } from "./ui/card";
import { FileDropzone } from "./FileDropzone";
import { CopiesInput } from "./CopiesInput";
import { CheckSelect, CheckOption } from "./CheckSelect";
import {
  ColorMode,
  Finishing,
  PageMode,
  MATERIAS,
  MATERIA_OUTRO,
  MATERIA_OUTRO_MAX,
  TURMA_OUTRO,
  TURMA_OUTRO_MAX,
  TURMAS_POR_SEGMENTO,
  SEGMENTOS_VALIDOS,
  ROTULOS_SEGMENTO,
  normalizarSegmentos,
  rotuloSegmentos,
  segmentoDaTurma,
} from "./types";
import { getStoredSession } from "./LoginScreen";
import { Printer } from "lucide-react";
import { toast } from "sonner";

export type SubmissionDraft = {
  // "aula" = envio de coordenador (matéria/turma); "diretoria" = envio
  // institucional (assunto + área). Define o texto da confirmação.
  kind: "aula" | "diretoria";
  subject: string;
  turma: string;
  copies: number;
  color: ColorMode;
  pageMode: PageMode;
  finishing: Finishing;
  fileName: string;
  file?: File;
  segmento?: string;
};

type Props = {
  onReview: (draft: SubmissionDraft) => void;
};

export function SubmissionForm({ onReview }: Props) {
  // `subject` guarda a caixa marcada — uma das matérias da lista ou o rótulo
  // "Outro". Quando é "Outro", o que vale é `outraMateria`; o rótulo em si
  // nunca é enviado.
  const [subject, setSubject] = useState("");
  const [outraMateria, setOutraMateria] = useState("");
  const [turma, setTurma] = useState("");
  // Texto da opção "Outro" da turma (uso próprio, reunião de pais...) —
  // como na matéria, o rótulo nunca é enviado, só o que for digitado aqui.
  const [outraTurma, setOutraTurma] = useState("");
  const [copies, setCopies] = useState(1);
  const [color, setColor] = useState<ColorMode>("PB");
  const [pageMode, setPageMode] = useState<PageMode>("Frente");
  const [finishing, setFinishing] = useState<Finishing>("Normal");
  const [file, setFile] = useState<File | null>(null);
  // Segmentos cadastrados da conta — pode ser mais de um (coordenador de
  // área que dá aula no Fund. I e no Fund. II). Sessões antigas trazem só
  // `segmento` (código único); normalizarSegmentos aceita os dois formatos.
  const segmentosConta = useMemo(() => {
    const sessao = getStoredSession();
    return normalizarSegmentos(
      sessao?.segmentos && sessao.segmentos.length > 0 ? sessao.segmentos : sessao?.segmento,
    );
  }, []);
  // Pré-selecionado SÓ quando a conta tem um único segmento cadastrado — é
  // informação, não fricção. Com vários, não existe "o" segmento para
  // presumir: a pessoa escolhe a cada envio, porque é o pedido que carrega
  // o segmento, não ela.
  const [segmento, setSegmento] = useState<string>(() =>
    segmentosConta.length === 1 ? segmentosConta[0] : "",
  );

  const ehOutro = subject === MATERIA_OUTRO;
  const materiaFinal = ehOutro ? outraMateria.trim() : subject;
  const ehOutraTurma = turma === TURMA_OUTRO;
  const turmaFinal = ehOutraTurma ? outraTurma.trim() : turma;

  // Marcar a turma já preenche o segmento correspondente (7º Ano -> Fund.
  // II): a turma determina o segmento da prova, e um carimbo errado faria o
  // pedido aparecer para a coordenação errada. O campo continua editável —
  // quem sabe de um caso especial pode trocar depois. A opção "Outro" não
  // tem segmento próprio: volta ao da conta (quando é um só) ou fica em
  // branco para a pessoa escolher — sem isso, o segmento da turma marcada
  // ANTES da troca ficava grudado em silêncio no pedido de uso próprio.
  const escolherTurma = (nome: string) => {
    setTurma(nome);
    const codigo = segmentoDaTurma(nome);
    setSegmento(codigo || (segmentosConta.length === 1 ? segmentosConta[0] : ""));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Avisos separados por campo: com caixas de seleção, "preencha todos os
    // campos" não diz qual delas ficou sem marcar.
    if (!subject) {
      toast.error("Marque a matéria da prova.");
      return;
    }
    if (ehOutro && !materiaFinal) {
      toast.error("Descreva a matéria no campo “Qual?”.");
      return;
    }
    if (!turma) {
      toast.error("Marque a turma que vai receber a prova.");
      return;
    }
    if (ehOutraTurma && !turmaFinal) {
      toast.error("Descreva o destino da impressão no campo “Qual?”.");
      return;
    }
    // Sem segmento o pedido ficaria "não definido" e escaparia da vista da
    // coordenação do segmento — obrigatório, mesmo que o normal seja ele já
    // vir preenchido pela turma marcada.
    if (!segmento) {
      toast.error(ehOutraTurma
        ? "Selecione o seu segmento — impressão de uso próprio também pertence a um."
        : "Selecione o segmento da prova.");
      return;
    }
    if (!file) {
      toast.error("Anexe o PDF da prova.");
      return;
    }

    onReview({
        kind: "aula",
        subject: materiaFinal,
        turma: turmaFinal,
        copies,
        color,
        pageMode,
        finishing,
        fileName: file.name,
        file: file,
        segmento: segmento || undefined,
    });
  };

  const SegBtn = ({ value, label }: { value: ColorMode; label: string }) => (
    <button
      type="button"
      onClick={() => setColor(value)}
      className={`flex-1 h-10 rounded-md border transition ${
        color === value
          ? "bg-[var(--brand-blue)] text-white border-[var(--brand-blue)]"
          : "bg-white text-slate-700 border-[var(--brand-border)] hover:bg-slate-50"
      }`}
    >
      {label}
    </button>
  );

  return (
    <Card className="p-8 border-[var(--brand-border)] shadow-sm">
      <div className="mb-6">
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a" }}>Nova Solicitação de Impressão</h2>
        <p className="text-slate-500 mt-1">Marque a matéria e a turma, e anexe o PDF</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-3">
          <Label>Matéria / Disciplina</Label>
          <CheckSelect
            label="Matéria / Disciplina"
            value={subject}
            onChange={setSubject}
            className="grid-cols-2 sm:grid-cols-3"
          >
            {MATERIAS.map((materia) => (
              <CheckOption key={materia} value={materia} />
            ))}
            <CheckOption value={MATERIA_OUTRO} label="Outro…" />
          </CheckSelect>

          {/* Só aparece com "Outro" marcado — é a única entrada de texto que
              sobrou, para o que não é matéria regular (capa de avaliação,
              simulado, recuperação). */}
          {ehOutro && (
            <div className="space-y-2 pt-1">
              <Label htmlFor="outra-materia">Qual?</Label>
              <Input
                id="outra-materia"
                autoFocus
                value={outraMateria}
                onChange={(e) => setOutraMateria(e.target.value)}
                maxLength={MATERIA_OUTRO_MAX}
                placeholder="Ex: Capa das Avaliações Parciais — 2º Trimestre"
              />
            </div>
          )}
        </div>

        <div className="space-y-3">
          <Label>Turma</Label>
          <CheckSelect label="Turma" value={turma} onChange={escolherTurma} className="gap-4">
            {TURMAS_POR_SEGMENTO.map(({ segmento, turmas }) => (
              <div key={segmento} className="space-y-2">
                <p
                  className="text-slate-500"
                  style={{ fontSize: "0.7rem", letterSpacing: "0.1em", fontWeight: 600 }}
                >
                  {segmento.toUpperCase()}
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {turmas.map((nome) => (
                    <CheckOption key={nome} value={nome} />
                  ))}
                </div>
              </div>
            ))}
            {/* Nem toda impressão pertence a uma turma: material de uso
                próprio do professor, reunião de pais, formação... Mesmo
                arranjo do "Outro" da matéria — o rótulo não é enviado, só
                o texto do campo "Qual?". */}
            <div className="space-y-2">
              <p
                className="text-slate-500"
                style={{ fontSize: "0.7rem", letterSpacing: "0.1em", fontWeight: 600 }}
              >
                SEM TURMA
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <CheckOption value={TURMA_OUTRO} label="Outro…" />
              </div>
            </div>
          </CheckSelect>

          {ehOutraTurma && (
            <div className="space-y-2 pt-1">
              <Label htmlFor="outra-turma">Qual?</Label>
              <Input
                id="outra-turma"
                autoFocus
                value={outraTurma}
                onChange={(e) => setOutraTurma(e.target.value)}
                maxLength={TURMA_OUTRO_MAX}
                placeholder="Ex: Uso próprio — planejamento de aulas"
              />
            </div>
          )}
        </div>

        <div className="space-y-2">
          <Label>Segmento</Label>
          <Select value={segmento || undefined} onValueChange={setSegmento}>
            <SelectTrigger><SelectValue placeholder="Selecione o segmento" /></SelectTrigger>
            <SelectContent>
              {SEGMENTOS_VALIDOS.map((s) => (
                <SelectItem key={s} value={s}>{ROTULOS_SEGMENTO[s]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-slate-400" style={{ fontSize: "0.75rem" }}>
            {segmentosConta.length > 1
              ? `Sua conta participa de: ${rotuloSegmentos(segmentosConta)}. O campo acompanha a turma marcada — confira antes de enviar.`
              : "Preenchido automaticamente a partir da turma marcada — troque só se este envio for um caso especial."}
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          <CopiesInput value={copies} onChange={setCopies} />

          <div className="space-y-2">
            <Label>Modo de Página</Label>
            <Select value={pageMode} onValueChange={(v) => setPageMode(v as PageMode)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="Frente">Apenas Frente</SelectItem>
                <SelectItem value="FrenteVerso">Frente e Verso</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2 md:col-span-2">
            <Label>Tipo de Cor</Label>
            <div className="flex gap-2">
              <SegBtn value="PB" label="P/B (Preto e Branco)" />
              <SegBtn value="Colorida" label="Colorida" />
            </div>
          </div>

          <div className="space-y-2 md:col-span-2">
            <Label>Acabamento</Label>
            <Select value={finishing} onValueChange={(v) => setFinishing(v as Finishing)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="Normal">Normal</SelectItem>
                <SelectItem value="Grampeada">Grampeada</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Anexo da Prova</Label>
          <FileDropzone file={file} onChange={setFile} />
        </div>

        <Button
          type="submit"
          className="w-full h-14 bg-[var(--brand-blue)] hover:bg-[var(--brand-blue-hover)] text-white transition relative overflow-hidden"
          style={{ borderBottom: "4px solid var(--brand-red)" }}
        >
          <Printer size={18} className="mr-2" />
          Enviar para o TI &amp; Impressora
        </Button>
      </form>
    </Card>
  );
}
