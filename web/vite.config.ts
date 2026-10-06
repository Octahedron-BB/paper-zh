import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, type Plugin } from 'vite'
import { edgeTtsMiddleware } from './server/edgeTtsServer.ts'

function edgeTtsPlugin(): Plugin {
  return {
    name: 'edge-tts-server',
    configureServer(server) {
      server.middlewares.use(edgeTtsMiddleware())
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: './', // 适配 GitHub Pages 等相对路径部署
  plugins: [
    vue(),
    tailwindcss(),
    edgeTtsPlugin(),
  ],
})
