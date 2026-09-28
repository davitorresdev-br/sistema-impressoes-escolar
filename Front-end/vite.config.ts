import { defineConfig } from 'vite'
import path from 'path'
import { fileURLToPath } from 'url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'


function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id) {
      if (id.startsWith('figma:asset/')) {
        const filename = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', filename)
      }
    },
  }
}

// Define __dirname for ESM environment
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

export default defineConfig({
  plugins: [
    figmaAssetResolver(),
    // The React and Tailwind plugins are both required for Make, even if
    // Tailwind is not being actively used – do not remove them
    react(),
    tailwindcss(),
    // basicSsl() foi removido: ele colocava o front-end em HTTPS enquanto
    // o backend (Flask, app.py) continua em HTTP simples. O navegador
    // bloqueia chamadas de uma página HTTPS para uma API HTTP ("mixed
    // content"), o que impedia justamente o acesso pelos professores via
    // IP. Se um dia quiser HTTPS, o backend também precisa ser servido em
    // HTTPS com um certificado confiável.
  ],

  server: {
    host: true, // Permite acesso pelo IP/Domínio na rede
    port: 5173
  },
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },

  // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
  assetsInclude: ['**/*.svg', '**/*.csv'],
})
