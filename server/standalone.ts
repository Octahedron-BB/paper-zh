import http from 'node:http'
import { edgeTtsMiddleware } from './edgeTtsServer.ts'

const PORT = Number(process.env.PORT) || 3000
const middleware = edgeTtsMiddleware()

const server = http.createServer((req, res) => {
  middleware(req, res, () => {
    if (req.url === '/' || req.url === '/health') {
      res.writeHead(200, {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      })
      res.end(
        JSON.stringify({
          status: 'ok',
          service: 'paper-zh Edge-TTS Proxy Server',
          endpoint: '/api/edge-tts',
        })
      )
      return
    }
    res.writeHead(404, { 'Content-Type': 'text/plain' })
    res.end('Not Found')
  })
})

server.listen(PORT, () => {
  console.log(`=======================================================`)
  console.log(`🎉 [Edge-TTS Proxy] 本地反代服务已就绪！`)
  console.log(`📡 服务地址: http://localhost:${PORT}`)
  console.log(`🔗 代理接口: http://localhost:${PORT}/api/edge-tts`)
  console.log(`💡 提示：在 GitHub Pages 网页设置的 Edge-TTS 代理中填入此地址即可`)
  console.log(`=======================================================`)
})
