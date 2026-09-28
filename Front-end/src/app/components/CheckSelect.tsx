import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { Check } from "lucide-react";
import { cn } from "./ui/utils";

/**
 * Grupo de caixas de seleção com escolha ÚNICA.
 *
 * Na tela são caixas (quadrado + tique), como o formulário pede, mas o
 * comportamento é exclusivo: marcar uma desmarca a anterior. Por isso é
 * construído sobre o RadioGroup do Radix, e não sobre o Checkbox — o leitor
 * de tela anuncia "opção 3 de 15" e as setas do teclado andam entre as
 * opções, que é o que de fato acontece. Um grupo de checkboxes de verdade
 * prometeria marcar várias e não cumpriria.
 *
 * O layout (quantas colunas, como agrupar) fica com quem chama, via
 * `className` — aqui só mora a aparência e o comportamento de cada caixa.
 */

type GroupProps = {
  /** Valor marcado. String vazia = nada marcado ainda. */
  value: string;
  onChange: (valor: string) => void;
  /** Lido pelo leitor de tela como o nome do grupo (ex.: "Turma"). */
  label: string;
  className?: string;
  children: React.ReactNode;
};

export function CheckSelect({ value, onChange, label, className, children }: GroupProps) {
  return (
    <RadioGroupPrimitive.Root
      value={value}
      onValueChange={onChange}
      aria-label={label}
      className={cn("grid gap-2", className)}
    >
      {children}
    </RadioGroupPrimitive.Root>
  );
}

type OptionProps = {
  /** O que vai para o banco. Também é o rótulo, se `label` não for passado. */
  value: string;
  label?: string;
  className?: string;
};

export function CheckOption({ value, label, className }: OptionProps) {
  return (
    <RadioGroupPrimitive.Item
      value={value}
      className={cn(
        "group flex w-full items-center gap-2.5 rounded-md border border-[var(--brand-border)]",
        "bg-white px-3 py-2.5 text-left outline-none transition hover:bg-slate-50",
        "focus-visible:ring-2 focus-visible:ring-[var(--brand-blue)] focus-visible:ring-offset-1",
        "data-[state=checked]:border-[var(--brand-blue)] data-[state=checked]:bg-blue-50",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-4 shrink-0 items-center justify-center rounded-[4px] border",
          "border-slate-300 bg-white text-white transition",
          "group-hover:border-slate-400",
          "group-data-[state=checked]:border-[var(--brand-blue)] group-data-[state=checked]:bg-[var(--brand-blue)]",
        )}
      >
        <RadioGroupPrimitive.Indicator>
          <Check size={12} strokeWidth={3} />
        </RadioGroupPrimitive.Indicator>
      </span>
      <span
        className="text-slate-700 group-data-[state=checked]:text-[var(--brand-blue)]"
        style={{ fontSize: "0.9rem" }}
      >
        {label ?? value}
      </span>
    </RadioGroupPrimitive.Item>
  );
}
