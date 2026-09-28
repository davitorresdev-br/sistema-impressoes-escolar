// ---------------------------------------------------------------------
// Endereço do servidor (Backend Flask).
// ---------------------------------------------------------------------
// EM PRODUÇÃO, vazio — ou seja, endereço RELATIVO ("/api/fila"). A tela
// compilada é servida pelo próprio servidor (ou pelo nginx na frente
// dele), então a API está sempre na MESMA origem da página: mesmo
// endereço, mesma porta, mesmo protocolo.
//
// Isso é o que faz o sistema funcionar em qualquer arranjo, sem editar
// este arquivo:
//   * Windows, acesso direto:      http://192.168.0.51:8080
//   * VM Ubuntu com nginx:         http://impressao.exemplo.com.br
//   * o mesmo, no dia do HTTPS:    https://impressao.exemplo.com.br
//
// Fixar a porta 8080 aqui (como era antes) quebraria os dois últimos: a
// página viria pela porta 80/443 e a API seria procurada na 8080, que
// atrás do nginx nem fica aberta para a rede.
//
// EM DESENVOLVIMENTO (`npm run dev`) é diferente: o Vite serve a tela na
// 5173 e o app.py responde na 8080, então aí sim é preciso o endereço
// completo. `import.meta.env.DEV` é o que separa os dois casos — ele é
// verdadeiro só no servidor de desenvolvimento do Vite.
export const API_BASE_URL = import.meta.env.DEV
  ? `http://${window.location.hostname}:8080`
  : "";
