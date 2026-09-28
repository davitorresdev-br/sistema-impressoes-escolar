import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { SubmissionDraft } from "./SubmissionForm";
import { COLOR_LABELS, PAGE_MODE_LABELS, rotuloSegmento } from "./types";
import { Printer, Loader2 } from "lucide-react";

type Props = {
  draft: SubmissionDraft | null;
  isSubmitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function ConfirmationModal({ draft, isSubmitting, onCancel, onConfirm }: Props) {
  if (!draft) return null;
  return (
    <Dialog open={!!draft} onOpenChange={(o) => !o && !isSubmitting && onCancel()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-50 border border-blue-100 text-[var(--brand-blue)] flex items-center justify-center">
              <Printer size={20} />
            </div>
            <DialogTitle style={{ fontSize: "1.25rem" }}>Confirmação de Impressão</DialogTitle>
          </div>
        </DialogHeader>

        <div className="space-y-4">
          {draft.kind === "diretoria" ? (
            <p className="text-slate-700" style={{ lineHeight: 1.6 }}>
              Você confirma o envio do documento{" "}
              <span className="text-[var(--brand-blue)]" style={{ fontWeight: 600 }}>{draft.subject}</span>{" "}
              (Diretoria — área <span style={{ fontWeight: 600 }}>{draft.turma}</span>){" "}
              com <span style={{ fontWeight: 600 }}>{draft.copies}</span>{" "}
              {draft.copies === 1 ? "cópia" : "cópias"}?
            </p>
          ) : (
            <p className="text-slate-700" style={{ lineHeight: 1.6 }}>
              Você confirma o envio da impressão da matéria{" "}
              <span className="text-[var(--brand-blue)]" style={{ fontWeight: 600 }}>{draft.subject}</span>{" "}
              para a turma <span className="text-[var(--brand-blue)]" style={{ fontWeight: 600 }}>{draft.turma}</span>{" "}
              com <span style={{ fontWeight: 600 }}>{draft.copies}</span>{" "}
              {draft.copies === 1 ? "cópia" : "cópias"}?
            </p>
          )}

          <div className="rounded-lg border border-dashed border-[var(--brand-border)] bg-slate-50 p-4 space-y-3">
            <p className="text-slate-500" style={{ fontSize: "0.75rem", letterSpacing: "0.1em", fontWeight: 600 }}>
              RESUMO DA SOLICITAÇÃO
            </p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="bg-white">{PAGE_MODE_LABELS[draft.pageMode]}</Badge>
              <Badge variant="outline" className="bg-white">{draft.finishing}</Badge>
              <Badge variant="outline" className="bg-white">{COLOR_LABELS[draft.color]}</Badge>
              <Badge variant="outline" className="bg-white">
                {draft.copies} {draft.copies === 1 ? "cópia" : "cópias"}
              </Badge>
              {/* Nada sobre "metade do papel" aqui: falar de folhas na hora
                  de confirmar as CÓPIAS confundia — lia-se como "vai sair
                  metade do que pedi". O total real em folhas aparece depois
                  do envio (aviso de confirmação) e na coluna da fila, onde
                  já não há dúvida sobre o que foi solicitado. */}
              {draft.kind === "aula" && draft.segmento && (
                <Badge variant="outline" className="bg-white">{rotuloSegmento(draft.segmento)}</Badge>
              )}
            </div>
            <div className="text-slate-600" style={{ fontSize: "0.85rem" }}>
              Arquivo: <span style={{ fontWeight: 500, color: "#0f172a" }}>{draft.fileName}</span>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onCancel} disabled={isSubmitting}>
            Ajustar Dados
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isSubmitting}
            className="bg-[var(--brand-blue)] hover:bg-[var(--brand-blue-hover)] text-white disabled:opacity-70"
          >
            {isSubmitting ? (
              <>
                <Loader2 size={16} className="mr-2 animate-spin" />
                Aguardando...
              </>
            ) : (
              "Confirmar Envio"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
