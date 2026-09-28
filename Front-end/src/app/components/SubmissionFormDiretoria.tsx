import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Card } from "./ui/card";
import { FileDropzone } from "./FileDropzone";
import { SubmissionDraft } from "./SubmissionForm";
import { CopiesInput } from "./CopiesInput";
import { ColorMode, Finishing, PageMode, Role, AREA_DO_CARGO } from "./types";
import { Printer, Building2 } from "lucide-react";
import { toast } from "sonner";

type Props = {
  // Cargo de quem está logado — define a área exibida (Administrativa /
  // Pedagógica). A área "de verdade" é reconfirmada pelo servidor a partir
  // do token; aqui é só para mostrar ao usuário.
  role: Role;
  onReview: (draft: SubmissionDraft) => void;
};

export function SubmissionFormDiretoria({ role, onReview }: Props) {
  const area = AREA_DO_CARGO[role] ?? "Institucional";

  const [assunto, setAssunto] = useState("");
  const [copies, setCopies] = useState(1);
  const [color, setColor] = useState<ColorMode>("PB");
  const [pageMode, setPageMode] = useState<PageMode>("Frente");
  const [finishing, setFinishing] = useState<Finishing>("Normal");
  const [file, setFile] = useState<File | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!assunto.trim() || !file) {
      toast.error("Informe o assunto do documento e anexe o PDF.");
      return;
    }
    onReview({
      kind: "diretoria",
      subject: assunto,   // vai como "assunto" / matéria do pedido
      turma: area,        // exibição; o servidor define a área pelo cargo
      copies,
      color,
      pageMode,
      finishing,
      fileName: file.name,
      file,
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
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a" }}>Envio da Diretoria</h2>
        <p className="text-slate-500 mt-1">Documento institucional — sem vínculo com turma</p>
      </div>

      {/* Área automática, vinda do cargo */}
      <div className="mb-5 flex items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
        <Building2 size={18} className="text-[var(--brand-blue)]" />
        <p className="text-slate-700" style={{ fontSize: "0.9rem" }}>
          Área <strong>{area}</strong> — definida automaticamente pelo seu cargo.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="assunto">Assunto / Descrição do documento</Label>
          <Input
            id="assunto"
            value={assunto}
            onChange={(e) => setAssunto(e.target.value)}
            placeholder="Ex: Comunicado aos pais — reunião"
          />
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
          <Label>Documento (PDF)</Label>
          <FileDropzone file={file} onChange={setFile} />
        </div>

        <Button
          type="submit"
          className="w-full h-14 bg-[var(--brand-blue)] hover:bg-[var(--brand-blue-hover)] text-white transition relative overflow-hidden"
          style={{ borderBottom: "4px solid var(--brand-red)" }}
        >
          <Printer size={18} className="mr-2" />
          Enviar para o Departamento de Impressão
        </Button>
      </form>
    </Card>
  );
}
