# Edge-TTS 反代部署指南 (Cloudflare Worker 极速免费方案)

由于微软 Edge-TTS 原生协议依赖特定非标准浏览器标头（如 `Origin: chrome-extension://...` 与动态时间哈希 `Sec-MS-GEC`），在 GitHub Pages 等纯静态网页环境中，直接通过客户端浏览器调用会被微软服务器拦截。

部署一个专属的 **Cloudflare Worker** 反向代理是最推荐的解决方案：
- **完全免费**：Cloudflare 免费版提供每日 100,000 次请求，个人与实验室日常使用完全够用。
- **免维护、全球边缘网络**：无需购买服务器，无需安装 Docker。
- **高拟真体验**：还原完整词级时间戳高亮与原生正版微软晓臻、云希等声音。

---

## 🚀 3 步极速部署（约 1 分钟）

### 第一步：创建 Cloudflare Worker
1. 访问并登录 [Cloudflare 控制台](https://dash.cloudflare.com/)。
2. 在左侧菜单点击 **Compute (Workers) -> Workers & Pages**。
3. 点击 **Create application** (或 **Create Worker**)。
4. 给 Worker 取一个名称（如 `edge-tts-proxy`），然后直接点击右下角的 **Deploy**（部署）。

### 第二步：粘贴代理代码
1. 部署完成后，在当前页面点击 **Edit code**（编辑代码）。
2. 在左侧代码编辑器中，把默认的代码全部删除。
3. 打开本项目中的 [`cloudflare/edge-tts-worker.js`](./edge-tts-worker.js)，复制全部内容，粘贴到 Cloudflare 编辑器中。
4. 点击右上角的 **Deploy**（保存并部署）。

### 第三步：填入学术伴读 Web 网页
1. 部署成功后，返回 Worker 概览页，复制分配给你的 Worker 访问域名，例如：
   `https://edge-tts-proxy.yourname.workers.dev`
2. 打开你的学术伴读 Web 页面（GitHub Pages 网址或本地页面），点击右上角 **⚙️ 设置**。
3. 伴读语音合成引擎选择 **Edge-TTS**。
4. 在 **Edge-TTS 代理 URL** 输入框中填入：
   ```text
   https://edge-tts-proxy.yourname.workers.dev/api/edge-tts
   ```
5. 点击 **🔊 试听发音** —— 即可听到纯正自然的台湾·晓臻伴读声音！

---

## 🖥️ 备选方案：本地或私有服务器部署 (Node.js)

如果你希望在本地常驻或自己的 VPS 上运行反代服务：

```bash
# 启动本地/服务器代理服务（默认端口 3000）
npm run server
```

服务就绪后，在伴读网页设置中填入你的服务器地址即可：
`http://localhost:3000/api/edge-tts` 或 `http://your-vps-ip:3000/api/edge-tts`
