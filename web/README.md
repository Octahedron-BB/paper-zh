# paper-zh 学术文献中文伴读工作台 (Web 版)

基于 **Vue 3 + TypeScript + TailwindCSS** 构建的学术文献分层伴读与有声学习系统。无需安装 Python 依赖，浏览器打开即用，**数据 100% 运行并保存在本地，零隐私泄露风险**。

---

## 🌐 在线体验（免安装，打开即用）

> 🔗 **在线伴读工作台网址**：  
> ### 👉 **[https://octahedron-bb.github.io/paper-zh/](https://octahedron-bb.github.io/paper-zh/)** 👈

*（推荐使用 Chrome / Edge / Safari 浏览器访问）*

---

## 💡 核心特性

- **100% 隐私安全与本地优先（Local-First）**：
  - 您的 API Key、上传的文献全文、生成的翻译稿件与朗读音频**全部保存在您的浏览器本地（localStorage / IndexedDB）**，无服务器中转与存储。
- **最新学术综述雷达（PubMed Review Feed）**：
  - 自动抓取 Nature Reviews 等顶级期刊近 7 天 / 近 14 天 / 近 30 天最新权威综述；
  - 支持一键 AI 提炼中文标题与机制速览，本地持久化缓存，刷新切页不丢失。
- **双输入源智能解析**：
  - **HTML 语义网页优先**：直接拖拽期刊官网 HTML 网页，分段精度 100%，保留标题与天然段落；
  - **PDF 智能提取**：浏览器本地解析，自适应滤除页眉页脚与杂质文本。
- **4 线程并发极速生成**：
  - 双语学术全译与口语化伴读讲稿并发改写，处理 100+ 段落综述仅需 2~3 分钟。
- **沉浸式伴读阅读器**：
  - 毫秒级零漂移时间轴，微软 Edge-TTS 真人拟真发音；
  - 逐句卡拉OK高亮跟随，支持“点哪读哪”，中英对照 / 口语讲稿 / 忠实译文多视图自由切换。
- **支持 Mac 本地模型（GPU 硬件加速 / 纯离线）**：
  - 可一键连接电脑本地 Ollama（如 Qwen 2.5 / DeepSeek R1），免 API 费用且纯离线运行。
- **本地个人学术书架**：
  - 一键永久收藏制作好的文献，支持导出为单文件自包含 HTML，脱机随时阅读。

---

## 📖 使用指南

### 1. 配置模型（首次使用）
点击网页右上角 **「设置」**：
- **云端大模型**：填入您的 DeepSeek、OpenAI 或 Gemini API Key；
- **本地大模型（可选）**：若电脑安装了 Ollama，在设置中选择 Custom 并点击「⚡ 一键填入 Ollama 本地模型」，即可调用电脑 GPU 本地算力；
- **朗读音色**：选择您喜欢的伴读人声（默认推荐：微软晓臻 / 台湾自然腔，或晓晓 / 普通话生动女声）。

### 2. 获取与导入文献
- **浏览最新综述**：在首页综述雷达中直接查看近期发表的 Nature Reviews 文献；
- **上传本地文献**：直接将文献官网保存的 `.html` 网页或官方 `.pdf` 文件拖拽至顶部上传区。

### 3. 开始生成伴读
点击文献卡片下方的 **「制作伴读」**：
- 系统将并发执行分段、专业术语替换、学术全译、口语讲稿改写与语音合成；
- 生成完毕后自动保存至您的「本地书架」。

### 4. 伴读学习与导出
- 戴上耳机，点击底部播放栏即可开始朗读；
- 点击正文中任意句子即可实现“点哪读哪”精准跳转；
- 点击右上角「导出」可将伴读网页保存为单文件 HTML 发送至手机或平板脱机学习。

---

## 💻 本地运行（如需在电脑本地开发或离线部署）

如果您希望在电脑本地克隆运行：

```bash
# 1. 克隆 web 分支
git clone -b web https://github.com/Octahedron-BB/paper-zh.git
cd paper-zh/web

# 2. 安装依赖
npm install

# 3. 启动本地开发服务
npm run dev
```

启动后在浏览器打开 `http://localhost:5174/` 即可。

---

## 📂 代码目录与架构介绍

本项目遵循清晰的模块化与分层设计：

```text
web/
├── index.html                  # 单页应用入口 HTML（自适应视口与字体）
├── vite.config.ts              # Vite 配置文件（已配置 base: './' 相对路径与 Edge-TTS 中间件）
├── package.json                # 项目依赖规范（Vue 3、TailwindCSS、pdfjs-dist、idb-keyval 等）
│
├── server/                     # 本地服务端开发支持
│   └── edgeTtsServer.ts        # Node.js 微软 Edge-TTS Sec-MS-GEC 签名代理中间件
│
├── public/                     # 静态公共资源
│
└── src/                        # 前端核心业务源码
    ├── App.vue                 # 根组件（顶栏导航、全局深色模式、键盘快捷键）
    ├── main.ts                 # Vue 应用挂载入口与样式引入
    │
    ├── views/                  # 核心功能页面
    │   ├── FeedView.vue        # 【文献速览】PubMed 综述雷达、时间窗口筛选、一键 AI 导读、文件上传
    │   ├── ReaderView.vue      # 【伴读阅读器】沉浸式多栏伴读视窗、多视图切换、音频精确高亮
    │   └── LibraryView.vue     # 【个人书架】已制作文献列表、历史记录、一键继续阅读与 HTML 导出
    │
    ├── components/             # 通用交互组件
    │   ├── SettingsModal.vue   # 【设置弹窗】LLM 服务商 / 本地 Ollama 切换、TTS 引擎与音色管理
    │   ├── PipelineModal.vue   # 【流水线弹窗】4 线程并发进度追踪、各阶段详细日志与试跑模式
    │   └── PlayerBar.vue       # 【底栏播放控制器】播放/暂停、快进快退、倍速调节与进度滑块
    │
    ├── store/                  # 本地持久化状态
    │   ├── settings.ts         # 用户设置状态（存储于 localStorage，0 云端泄露）
    │   └── library.ts          # 文献书架持久化（存储于 IndexedDB，支持大文件与离线音视频）
    │
    └── core/                   # 核心算法与底层引擎
        ├── types.ts            # 全局 TypeScript 接口与类型定义
        ├── pubmed.ts           # NCBI PubMed ESearch/EFetch 接口对接与综述智能提取
        ├── segmentHtml.ts      # Nature 等期刊语义 HTML 高保真分段解析引擎
        ├── pdfParser.ts        # 浏览器端纯前端 PDF 文本版面智能分段抽取
        ├── llm.ts              # 通用大模型客户端（OpenAI / DeepSeek / Gemini / 本地 Ollama）
        ├── glossary.ts         # 专业术语匹配与语境保护的零成本硬替换引擎
        ├── abbrev.ts           # 文献首字母缩写与权威全称定义自动抽取算法
        ├── polyphone.ts        # 汉字多音字与医学专有名词发音清洗模块
        ├── edgeTts.ts          # 微软 Edge-TTS 客户端通信与时间戳提取
        ├── pipeline.ts         # 4 线程高并发流水线调度器（翻译/改写/语音合成/零漂移对齐）
        ├── readerBuilder.ts    # 自包含单文件 Web Reader HTML 代码打包生成器
        └── prompts.ts          # 学术双语翻译与口语化伴读讲稿 Prompt 模板
```
