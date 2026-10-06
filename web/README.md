# paper-zh 纯前端学术文献伴读工作台 (Web App)

基于 **Vue 3 + TypeScript + Vite + TailwindCSS** 构建的 100% 纯前端、Local-First 学术文献双向伴读与有声系统。

---

## 🌟 核心亮点

- **100% 本地优先与隐私安全（Local-First）**：
  - 你的 API Key、上传的论文 PDF/HTML、生成的翻译讲稿与音频**全部保存在本地浏览器（localStorage / IndexedDB）**，无需任何 VPS 后端数据库，零数据泄露风险。
- **最新学术综述雷达（PubMed Review Feed）**：
  - 直连 NCBI PubMed E-Utilities，近 7 天 / 近 14 天 / 近 30 天阶梯式动态拉取 Nature Reviews 等顶级期刊综述；
  - 一键 AI 智能提炼中文标题与机制速览，本地持久化缓存，刷新切页不丢失。
- **双输入源智能解析**：
  - **HTML 语义网页优先**：完美保留学术期刊标题、段落、公式与图注天然层级；
  - **PDF 自动分段提取**：基于 `pdfjs-dist` 本地客户端解析，自适应滤除页眉页脚与杂质文本。
- **高并发极速流水线（比串行提速 75%+）**：
  - **忠实全译**：4 线程并发执行，专业术语自动挖掘与规范替换；
  - **口语改写**：4 线程并发重构，统计学数字听觉化重塑、多音字发音清洗；
  - **语音合成**：3 线程并发合成，支持微软 Edge-TTS 真实神经拟真音色与浏览器原生 Web Speech 离线引擎。
- **毫秒级零漂移时间轴与卡拉OK高亮**：
  - Web Audio API 物理音频解码严格对齐，彻底杜绝长篇文献音画脱节；
  - 句子级智能聚合，段落排版自然流畅，支持“点哪读哪”、中英对照 / 讲稿 / 译文视图随意切换。
- **支持电脑本地模型（Mac GPU / Ollama 硬件加速）**：
  - 一键直连本机 `http://localhost:11434/v1`（如 Qwen 2.5 / DeepSeek R1），完全离线、免 API 费用、利用 Mac 统一内存与 Metal GPU 加速。
- **本地专属文献书架**：
  - 基于 IndexedDB 永久保存已制作的伴读文献，随时温故知新，支持一键导出单文件自包含 HTML。

---

## 🚀 本地开发与调试

### 1. 安装依赖
```bash
cd web
npm install
```

### 2. 启动开发服务器
```bash
npm run dev
```
启动后在浏览器打开 `http://localhost:5174/`（内置 Edge-TTS Sec-MS-GEC 开发服务中间件）。

### 3. 打包构建
```bash
npm run build
```
产物将输出至 `web/dist/` 目录，已配置相对路径 `base: './'`，开箱即用支持任意静态托管平台。

---

## 🌐 GitHub Pages 自动部署指南

本项目已配置 GitHub Actions 自动化工作流（`.github/workflows/deploy.yml`）：

1. **设置 GitHub Pages 部署源**：
   - 打开 GitHub 仓库页面：`https://github.com/Octahedron-BB/paper-zh`
   - 进入 **Settings** -> 侧边栏 **Pages**
   - 在 **Build and deployment** 下方的 **Source** 下拉菜单中选择：**GitHub Actions**
2. **触发自动部署**：
   - 将 `web` 分支 push 到 GitHub：
     ```bash
     git push -u origin web
     ```
   - GitHub Actions 将自动触发 `Deploy Web App to GitHub Pages` 工作流，完成依赖安装、构建并发布；
3. **访问线上网页**：
   - 部署完成后，在线地址通常为：
     `https://octahedron-bb.github.io/paper-zh/`
