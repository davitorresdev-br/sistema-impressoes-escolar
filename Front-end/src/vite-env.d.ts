/// <reference types="vite/client" />

// Traz os tipos que o Vite injeta em tempo de build — entre eles o
// `import.meta.env`, usado em src/app/config.ts para distinguir o servidor
// de desenvolvimento (Vite na 5173, API à parte na 8080) da tela compilada
// (API na mesma origem da página). Sem este arquivo, o `npm run typecheck`
// acusa "Property 'env' does not exist on type 'ImportMeta'".
