import { useEffect, useState } from "react";
import { Minus, Plus } from "lucide-react";
import { Label } from "./ui/label";

type Props = {
  value: number;
  onChange: (copias: number) => void;
};

/**
 * Campo de número de cópias.
 *
 * Guarda TEXTO enquanto a pessoa digita, não número, e permite o campo
 * vazio. Normalizar a cada tecla (`parseInt(valor) || 1`) faria o "1" voltar
 * assim que fosse apagado, obrigando a digitar antes de apagar.
 *
 * A normalização acontece só ao sair do campo. Enquanto está vazio, o
 * formulário continua com 1 — e a tela de confirmação mostra o número antes
 * de qualquer impressão, então não há risco de enviar algo diferente do que
 * a pessoa viu.
 */
export function CopiesInput({ value, onChange }: Props) {
  const [texto, setTexto] = useState(String(value));

  // Mantém o texto em dia quando o valor muda de fora (ex.: o formulário é
  // limpo depois de um envio).
  useEffect(() => {
    setTexto((atual) => (parseInt(atual, 10) === value ? atual : String(value)));
  }, [value]);

  const alterar = (bruto: string) => {
    // Só dígitos. Vazio é permitido de propósito — é o estado intermediário
    // de quem está apagando para digitar outro número.
    const limpo = bruto.replace(/\D/g, "");
    setTexto(limpo);
    onChange(limpo === "" ? 1 : Math.max(1, parseInt(limpo, 10)));
  };

  const normalizar = () => {
    const n = Math.max(1, parseInt(texto, 10) || 1);
    setTexto(String(n));
    onChange(n);
  };

  const somar = (delta: number) => {
    const n = Math.max(1, (parseInt(texto, 10) || 1) + delta);
    setTexto(String(n));
    onChange(n);
  };

  return (
    <div className="space-y-2">
      <Label htmlFor="copias">Número de Cópias</Label>
      <div className="flex items-center h-11 rounded-md border border-[var(--brand-border)] overflow-hidden">
        <button
          type="button"
          aria-label="Uma cópia a menos"
          onClick={() => somar(-1)}
          className="w-11 h-full flex items-center justify-center text-slate-600 hover:bg-slate-100 transition"
        >
          <Minus size={16} />
        </button>
        <input
          id="copias"
          // "text" com inputMode numérico em vez de type="number": as setinhas
          // nativas eram redundantes com os botões +/- ao lado, e o campo
          // numérico do navegador atrapalha o estado vazio durante a edição.
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={texto}
          onChange={(e) => alterar(e.target.value)}
          onBlur={normalizar}
          className="flex-1 h-full text-center bg-transparent outline-none"
        />
        <button
          type="button"
          aria-label="Uma cópia a mais"
          onClick={() => somar(1)}
          className="w-11 h-full flex items-center justify-center text-slate-600 hover:bg-slate-100 transition"
        >
          <Plus size={16} />
        </button>
      </div>
    </div>
  );
}
