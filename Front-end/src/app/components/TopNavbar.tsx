import * as React from "react";
import { Role, ROLE_LABELS, podeVerRelatorios } from "./types";
import { Badge } from "./ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { ChevronDown, FileBarChart, KeyRound, LogOut, Printer, Send, Users } from "lucide-react";

type View = "dashboard" | "queue" | "report" | "admin";

type Props = {
  view: View;
  setView: (v: View) => void;
  role: Role;
  setRole: (r: Role) => void;
  isSuperAdmin: boolean;
  currentUser: string;
  // Rótulo do segmento quando o escopo em vigor é justamente esse segmento
  // (uma COORDENACAO fora de GERAL) — null nos demais casos.
  segmentoRotulo?: string | null;
  pendingCount: number;
  onChangePassword: () => void;
  onLogout: () => void;
};

export function TopNavbar({ view, setView, role, setRole, isSuperAdmin, currentUser, segmentoRotulo, pendingCount, onChangePassword, onLogout }: Props) {
  // A navegação rola na horizontal quando não cabe (rótulos nunca quebram).
  // A barra de rolagem nativa destoaria do topo azul, então ela fica
  // escondida e quem indica "tem mais aba ali" são os esmaecimentos nas
  // bordas — visíveis só no lado que tem conteúdo escondido.
  const navRef = React.useRef<HTMLElement>(null);
  const [fade, setFade] = React.useState({ esquerda: false, direita: false });

  const atualizarFades = React.useCallback(() => {
    const el = navRef.current;
    if (!el) return;
    const esquerda = el.scrollLeft > 2;
    const direita = el.scrollLeft + el.clientWidth < el.scrollWidth - 2;
    setFade((f) => (f.esquerda === esquerda && f.direita === direita ? f : { esquerda, direita }));
  }, []);

  React.useEffect(() => {
    atualizarFades();
    const el = navRef.current;
    if (!el) return;
    const observador = new ResizeObserver(atualizarFades);
    observador.observe(el);
    // O listener de resize da janela é cinto-e-suspensório: cobre casos em
    // que o ResizeObserver não notifica (zoom, emulação de viewport).
    window.addEventListener("resize", atualizarFades);
    return () => {
      observador.disconnect();
      window.removeEventListener("resize", atualizarFades);
    };
  }, [atualizarFades]);

  // As abas mudam com o cargo (Relatórios/Usuários) e o contador da fila
  // muda a largura — reavalia os fades quando isso acontece.
  React.useEffect(() => {
    atualizarFades();
  }, [role, pendingCount, atualizarFades]);

  // Roda do mouse rola as abas na horizontal — sem isso, quem usa mouse só
  // alcançaria as abas escondidas arrastando ou com Shift+roda.
  const rolarComRoda = (e: React.WheelEvent) => {
    const el = navRef.current;
    if (!el || el.scrollWidth <= el.clientWidth) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) el.scrollLeft += e.deltaY;
  };

  // `labelCurto` entra abaixo de xl: "Enviar Impressão" vira "Enviar" — o
  // ícone já diz do que se trata. É o que faz as quatro abas do T.I.
  // caberem sem rolagem em telas comuns; o scroll com fades fica só como
  // rede de segurança para janelas realmente estreitas.
  const NavLink = ({ id, label, labelCurto, icon, badge }: { id: View; label: string; labelCurto?: string; icon: React.ReactNode; badge?: number }) => {
    const active = view === id;
    return (
      <button
        onClick={() => setView(id)}
        // whitespace-nowrap + shrink-0: sem isso, em janela mais estreita o
        // rótulo quebrava em duas linhas dentro do botão de altura fixa e a
        // linha vermelha do item ativo atravessava a segunda linha do texto.
        className={`relative flex items-center gap-2 px-3 h-10 rounded-md transition whitespace-nowrap shrink-0 ${
          active ? "bg-white/10 text-white" : "text-white/70 hover:text-white hover:bg-white/5"
        }`}
      >
        {icon}
        {/* O rótulo curto é permanente: com o crachá âmbar de cargo no
            topo (limitado a 1280px pelo max-w-7xl), "Enviar Impressão" por
            extenso não cabe junto das quatro abas do T.I. — e o ícone já
            carrega o contexto. O rótulo completo fica no title. */}
        <span title={label}>{labelCurto ?? label}</span>
        {badge && badge > 0 ? (
          <span className="ml-1 min-w-5 h-5 px-1.5 rounded-full bg-[var(--brand-red)] text-white flex items-center justify-center" style={{ fontSize: "0.7rem", fontWeight: 700 }}>
            {badge}
          </span>
        ) : null}
        {/* bottom-0 (não -bottom-px): com overflow-x-auto no nav, 1px fora
            do botão virava overflow vertical — a linha era clipada e o
            Windows chegava a mostrar uma barra de rolagem espúria. */}
        {active && <span className="absolute left-2 right-2 bottom-0 h-0.5 bg-[var(--brand-red)] rounded-full" />}
      </button>
    );
  };

  return (
    <header className="sticky top-0 z-30 bg-[var(--brand-blue)] text-white border-b-2 border-[var(--brand-red)]">
      <div className="max-w-7xl mx-auto px-4 lg:px-6 h-16 flex items-center gap-4">
        <div className="flex items-center gap-3 shrink-0">
          <div className="w-9 h-9 rounded-lg bg-white text-[var(--brand-blue)] flex items-center justify-center" style={{ fontWeight: 700 }}>IA</div>
          {/* xl (não md): abaixo de 1280px o nome por extenso disputava
              espaço com as quatro abas — o quadrado "IA" segura a
              identidade sozinho nessa faixa. */}
          <div className="hidden xl:block">
            <p style={{ fontSize: "0.875rem", fontWeight: 700, letterSpacing: "0.05em" }}>INSTITUTO ACALANTO DE ENSINO</p>
            <p className="opacity-70" style={{ fontSize: "0.7rem" }}>Portal de Impressão</p>
          </div>
        </div>

        {/* Espaçador esquerdo: junto com o gêmeo à direita, centraliza as
            abas no espaço entre o logotipo e o bloco do usuário. Em janela
            apertada os dois colapsam a zero e nada se sobrepõe. */}
        <div className="flex-1" />

        {/* min-w-0 + overflow-x-auto: com os rótulos em nowrap, uma janela
            estreita rola as abas na horizontal em vez de estourar o topo.
            A barra nativa fica escondida; os fades nas bordas (na cor da
            própria barra) fazem o papel de indicar o que está fora. */}
        <div className="relative min-w-0">
          <nav
            ref={navRef}
            onScroll={atualizarFades}
            onWheel={rolarComRoda}
            className="flex items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            <NavLink id="dashboard" label="Enviar Impressão" labelCurto="Enviar" icon={<Send size={16} />} />
            <NavLink id="queue" label="Fila de Impressão" labelCurto="Fila" icon={<Printer size={16} />} badge={pendingCount} />
            {/* Relatórios: TI, Diretoria (leitura) e Coordenação (travada no
                próprio segmento). Usuários: só o TI. */}
            {podeVerRelatorios(role) && (
              <NavLink id="report" label="Relatórios" icon={<FileBarChart size={16} />} />
            )}
            {role === "TI" && (
              <NavLink id="admin" label="Usuários" icon={<Users size={16} />} />
            )}
          </nav>
          {fade.esquerda && (
            <div aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-[var(--brand-blue)] to-transparent" />
          )}
          {fade.direita && (
            <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-[var(--brand-blue)] to-transparent" />
          )}
        </div>

        <div className="flex-1" />

        <div className="hidden md:flex items-center gap-3 shrink-0">
          {/* O crachá âmbar é O apresentador do cargo (o nome ao lado vem
              sem sufixo). Some só na faixa 768–1023px, onde nem "COORDENAÇÃO
              DE SEGMENTO" caberia junto das quatro abas. Quando o crachá de
              segmento está logo ao lado, o de cargo encurta para
              "COORDENAÇÃO" — o par inteiro lê "COORDENAÇÃO · Fundamental I
              e Fundamental II", sem repetir a palavra segmento (e sem
              estourar o teto de 1280px do topo). */}
          <Badge className="hidden lg:inline-flex bg-[var(--brand-amber)] text-slate-900 hover:bg-[var(--brand-amber)]" style={{ fontWeight: 600 }}>
            {segmentoRotulo && role === "COORDENACAO" ? "COORDENAÇÃO" : ROLE_LABELS[role]}
          </Badge>
          {/* Escopo em vigor, confirmado pelo servidor na última /api/fila —
              a coordenadora de segmento precisa ver isto sem adivinhar. O
              teto de largura protege o caso de dois segmentos ("Fundamental
              I e Fundamental II"); o texto completo fica no hover. */}
          {segmentoRotulo && (
            <Badge
              variant="outline"
              className="hidden lg:inline-flex border-white/30 text-white bg-white/10 max-w-[10rem]"
              title={segmentoRotulo}
            >
              <span className="truncate">{segmentoRotulo}</span>
            </Badge>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger className="inline-flex items-center gap-2 h-10 px-3 rounded-md text-white hover:bg-white/10 transition outline-none">
              <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center" style={{ fontSize: "0.75rem", fontWeight: 600 }}>
                {currentUser.split(" ").map((p) => p[0]).slice(0, 2).join("")}
              </div>
              {/* Truncado com o nome completo no hover — sem o sufixo de
                  cargo (que agora vive no crachá), sobra mais espaço para
                  o nome em si. */}
              <span className="max-w-[7rem] truncate lg:max-w-[8rem] xl:max-w-[10rem]" title={currentUser}>{currentUser}</span>
              <ChevronDown size={14} className="shrink-0" />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {/* Só o Admin (super_admin no banco de dados) vê e usa isso —
                  e continua vendo nos dois modos, já que depende de
                  isSuperAdmin e não do "role" que está sendo visualizado. */}
              {isSuperAdmin && (
                <>
                  <DropdownMenuLabel>Trocar Perfil (Admin)</DropdownMenuLabel>
                  <DropdownMenuItem onClick={() => setRole("COORDENADOR")}>
                    Coordenador de Área
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setRole("COORDENACAO")}>
                    Coordenação de Segmento
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setRole("DIRETOR_ADM")}>
                    Diretor Administrativo
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setRole("DIRETORA_PED")}>
                    Diretora Pedagógica
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setRole("TI")}>
                    Departamento de T.I.
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              {/* Toda conta é local (usuário/senha do servidor), então a
                  troca de senha vale para qualquer cargo — não só o T.I.,
                  que já tinha o reset pelo painel de usuários. */}
              <DropdownMenuItem onClick={onChangePassword}>
                <KeyRound className="mr-2 h-4 w-4" />
                <span>Trocar senha</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onLogout} className="text-red-600 font-medium">
                <LogOut className="mr-2 h-4 w-4" />
                <span>Sair</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}
