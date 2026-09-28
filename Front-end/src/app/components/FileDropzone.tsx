import { useRef, useState } from "react";
import { toast } from "sonner";
import { Check, FileText, UploadCloud, X } from "lucide-react";

type Props = {
  file: File | null;
  onChange: (f: File | null) => void;
};

export function FileDropzone({ file, onChange }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const accept = (f: File) => {
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Erro: Formato inválido. Apenas PDFs são aceitos.");
      return;
    }
    if (f.size > 50 * 1024 * 1024) {
      toast.error("Erro: Arquivo excede o limite de 50 MB.");
      return;
    }
    onChange(f);
  };

  if (file) {
    return (
      <div className="flex items-center gap-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 transition">
        <div className="w-12 h-12 rounded-lg bg-white border border-emerald-200 flex items-center justify-center text-[var(--brand-blue)]">
          <FileText size={22} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="truncate" style={{ fontWeight: 600, color: "#0f172a" }}>{file.name}</p>
          <p className="text-emerald-700 flex items-center gap-1" style={{ fontSize: "0.8rem" }}>
            <Check size={14} /> Arquivo pronto para envio · {(file.size / (1024 * 1024)).toFixed(2)} MB
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange(null)}
          className="w-8 h-8 rounded-full bg-white border border-emerald-200 text-slate-500 hover:text-[var(--brand-red)] hover:border-[var(--brand-red)] flex items-center justify-center transition"
          aria-label="Remover arquivo"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files?.[0];
        if (f) accept(f);
      }}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition ${
        dragging
          ? "border-[var(--brand-blue)] bg-blue-50"
          : "border-[var(--brand-border)] bg-slate-50 hover:bg-slate-100"
      }`}
      style={{ borderRadius: 12 }}
    >
      <div className="mx-auto w-14 h-14 rounded-full bg-white border border-[var(--brand-border)] flex items-center justify-center text-[var(--brand-blue)]">
        <UploadCloud size={26} />
      </div>
      <p className="mt-4" style={{ fontWeight: 600, color: "#0f172a" }}>
        Arraste o arquivo PDF aqui ou clique para selecionar
      </p>
      <p className="text-slate-500 mt-1" style={{ fontSize: "0.85rem" }}>
        Apenas arquivos PDF · Máx. 50 MB
      </p>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) accept(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
