import { useEffect, useState } from "react";
import { Card } from "./ui/card";
import { AlertTriangle, Clock, FileText, WifiOff } from "lucide-react";
import { API_BASE_URL } from "../config";

type Horario = {
  inicio: string;
  fim: string;
  so_dias_uteis: boolean;
  modo_desenvolvimento?: boolean;
  // Sinal de vida do agente de impressão. null = nunca houve sinal (não dá
  // para afirmar nada, então a tela não acusa nada).
  agente_online?: boolean | null;
  agente_visto_em?: string | null;
};

// Usado enquanto a resposta não chega, e se a API estiver fora do ar. Mesmos
// valores padrão de horario_impressao.py — se mudar lá, mude aqui.
const PADRAO: Horario = { inicio: "08:00", fim: "18:00", so_dias_uteis: false };

function horaDoSinal(iso?: string | null): string {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  return new Date(ms).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function InfoSidebar() {
  // O horário vem do servidor, nunca escrito à mão aqui: a tela não pode
  // anunciar uma faixa diferente da que o agente cumpre.
  const [horario, setHorario] = useState<Horario>(PADRAO);

  useEffect(() => {
    let ativo = true;
    const buscar = () =>
      fetch(`${API_BASE_URL}/api/horario`)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((dados) => {
          if (ativo) setHorario(dados);
        })
        .catch(() => {
          // Silencioso de propósito: o painel é informativo, e o padrão acima
          // já é uma resposta razoável. Não vale poluir a tela do professor.
        });
    buscar();
    // Reconsulta enquanto a tela está aberta: se a impressora cair no meio
    // do expediente, o aviso aparece sozinho, sem F5.
    const intervalo = setInterval(buscar, 60000);
    return () => {
      ativo = false;
      clearInterval(intervalo);
    };
  }, []);

  return (
    <div className="space-y-5">
      {/* IMPRESSORA FORA DO AR. Só aparece quando o servidor tem CERTEZA
          (já houve sinal do agente alguma vez e ele parou de chegar) —
          dizer "fora do ar" sem saber seria alarme falso. Isso muda a
          experiência de "o sistema não é confiável" para "o sistema me
          avisou": o pedido não se perde, só espera. */}
      {horario.agente_online === false && (
        <Card className="p-5 border-2 border-[var(--brand-red)] bg-red-50 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-white border border-red-200 text-[var(--brand-red)] flex items-center justify-center shrink-0">
              <WifiOff size={20} />
            </div>
            <div>
              <p style={{ fontWeight: 700, color: "#7f1d1d" }}>
                A impressora está fora do ar
                {horaDoSinal(horario.agente_visto_em) ? ` desde ${horaDoSinal(horario.agente_visto_em)}` : ""}
              </p>
              <p className="text-red-900/80 mt-1" style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>
                Seu pedido é registrado normalmente e será impresso quando o sistema
                voltar. O Departamento de T.I. já pode ver este aviso.
              </p>
            </div>
          </div>
        </Card>
      )}
      <Card className="p-6 border-[var(--brand-border)] shadow-sm">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-50 border border-amber-200 text-[var(--brand-amber)] flex items-center justify-center shrink-0">
            <AlertTriangle size={20} />
          </div>
          <div>
            <p style={{ fontWeight: 600, color: "#0f172a" }}>Suporte Técnico</p>
            <p className="text-slate-600 mt-1" style={{ fontSize: "0.9rem", lineHeight: 1.5 }}>
              Quaisquer dúvidas referentes à plataforma, entre em contato com o
              Departamento de T.I (Ramal <span style={{ fontWeight: 600 }}>1113</span>).
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-6 bg-[var(--brand-blue)] text-white border-0 shadow-sm relative overflow-hidden">
        <div className="absolute top-0 right-0 w-32 h-32 rounded-full bg-white/5 -translate-y-12 translate-x-12" />
        <div className="relative">
          <div className="flex items-center gap-2">
            <Clock size={20} />
            <p style={{ fontWeight: 600 }}>Horário de Funcionamento</p>
          </div>
          {/* Em modo de desenvolvimento a faixa não é respeitada — mostrar
              "08:00 às 18:00" aqui seria informar um horário que o agente
              está ignorando. */}
          {horario.modo_desenvolvimento ? (
            <p className="mt-3 opacity-90" style={{ lineHeight: 1.5 }}>
              Modo de desenvolvimento
              <br />
              <span style={{ fontSize: "1.25rem", fontWeight: 700 }}>Sem limite de horário</span>
            </p>
          ) : (
            <p className="mt-3 opacity-90" style={{ lineHeight: 1.5 }}>
              {horario.so_dias_uteis ? "Segunda a Sexta-feira" : "Todos os dias"}
              <br />
              <span style={{ fontSize: "1.25rem", fontWeight: 700 }}>
                {horario.inicio} às {horario.fim}
              </span>
            </p>
          )}

          <div className="h-px bg-white/20 my-5" />

          <div className="flex items-start gap-2">
            <FileText size={16} className="mt-0.5 shrink-0" />
            <p className="opacity-90" style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>
              <span style={{ fontWeight: 600 }}>Restrição:</span> é permitido apenas o
              envio de documentos salvos em PDF.
            </p>
          </div>
        </div>
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--brand-red)]" />
      </Card>
    </div>
  );
}
