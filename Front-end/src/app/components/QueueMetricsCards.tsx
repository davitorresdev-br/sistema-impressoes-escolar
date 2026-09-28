import { Card } from "./ui/card";
import { PrintJob } from "./types";
import { CheckCircle2, Clock, Printer } from "lucide-react";

type Props = { jobs: PrintJob[] };

export function QueueMetricsCards({ jobs }: Props) {
  const pending = jobs.filter((j) => j.status === "Pendente").length;
  const printing = jobs.filter((j) => j.status === "Imprimindo").length;
  // O card promete "últimas 24h" — então conta só o que foi entregue à
  // impressora nesse intervalo, não a história inteira. Concluídos antigos
  // sem carimbo de impressão (printedAt nulo) ficam de fora.
  const UM_DIA_MS = 24 * 60 * 60 * 1000;
  const completed = jobs.filter(
    (j) => j.status === "Concluído" && j.printedAt && Date.now() - j.printedAt < UM_DIA_MS,
  ).length;

  return (
    <div className="grid md:grid-cols-3 gap-5">
      <Card className="p-6 bg-white shadow-sm" style={{ borderLeft: "4px solid var(--brand-amber)" }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-slate-500" style={{ fontSize: "0.85rem", fontWeight: 600, letterSpacing: "0.05em" }}>PENDENTES</p>
            <p className="mt-2" style={{ fontSize: "2.25rem", fontWeight: 700, color: "#0f172a", lineHeight: 1 }}>{pending}</p>
            <p className="text-slate-500 mt-1" style={{ fontSize: "0.8rem" }}>aguardando processamento</p>
          </div>
          <div className="w-12 h-12 rounded-xl bg-amber-50 border border-amber-200 text-[var(--brand-amber)] flex items-center justify-center">
            <Clock size={22} />
          </div>
        </div>
      </Card>

      <Card className="p-6 bg-white shadow-sm" style={{ borderLeft: "4px solid var(--brand-blue)" }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-slate-500 flex items-center gap-2" style={{ fontSize: "0.85rem", fontWeight: 600, letterSpacing: "0.05em" }}>
              IMPRIMINDO
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--brand-blue)]" />
              </span>
            </p>
            <p className="mt-2" style={{ fontSize: "2.25rem", fontWeight: 700, color: "#0f172a", lineHeight: 1 }}>{printing}</p>
            <p className="text-slate-500 mt-1" style={{ fontSize: "0.8rem" }}>em produção agora</p>
          </div>
          <div className="w-12 h-12 rounded-xl bg-blue-50 border border-blue-100 text-[var(--brand-blue)] flex items-center justify-center">
            <Printer size={22} />
          </div>
        </div>
      </Card>

      <Card className="p-6 bg-white shadow-sm" style={{ borderLeft: "4px solid #10b981" }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-slate-500" style={{ fontSize: "0.85rem", fontWeight: 600, letterSpacing: "0.05em" }}>ENVIADAS</p>
            <p className="mt-2" style={{ fontSize: "2.25rem", fontWeight: 700, color: "#0f172a", lineHeight: 1 }}>{completed}</p>
            <p className="text-slate-500 mt-1" style={{ fontSize: "0.8rem" }}>entregues à impressora nas últimas 24h</p>
          </div>
          <div className="w-12 h-12 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-600 flex items-center justify-center">
            <CheckCircle2 size={22} />
          </div>
        </div>
      </Card>
    </div>
  );
}
