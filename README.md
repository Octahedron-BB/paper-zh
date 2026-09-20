# 文献 → 中文分层伴读与播客生成系统 (paper-zh)

将 Nature Reviews 等高密度英文学术综述 PDF，一键自动化转化为端到端的高质量中文分层伴读与播客有声系统：

1. **自包含 Web Reader 双向伴读网页**（`data/reader/<doc_id>.html`）—— **单文件零依赖、内嵌音频、逐句变色高亮、点句即播、移动端/PC 全自适应**
2. **高质量播客朗读音频**（`data/audio/`）—— **多音字发音清洗、毫秒级时间戳、LRC/VTT 字幕**
3. **轨A · 忠实全译**（`data/translation/`）—— 学术全译，逐段对照原文
4. **轨B · 口语讲稿**（`data/script/`）—— 听觉友好、无悬空图表、多音字规避的口语播客稿
5. **中英交错对照**（`data/interleave/`）—— VS Code 侧边栏沉浸式中英对照

---

## 目录

- [一、核心特性](#一核心特性)
- [二、快速开始](#二快速开始)
- [三、目录结构](#三目录结构)
- [四、产物矩阵与使用指南](#四产物矩阵与使用指南)
- [五、配置与定制指南](#五配置与定制指南)
  - [1. 术语表体系与缓存机制](#1-术语表体系与缓存机制)
  - [2. 多音字与专业发音清洗](#2-多音字与专业发音清洗)
- [六、质量检验与测试](#六质量检验与测试)
- [七、常见问题 (FAQ)](#七常见问题-faq)
- [八、排错与高级开发工具](#八排错与高级开发工具)
- [九、版权与数据安全说明](#九版权与数据安全说明)
- [十、开源许可](#十开源许可)

---

## 一、核心特性

- **端到端一键生成**：从原始 PDF 到包含音频的单文件伴读网页，单条命令全自动完成。
- **自包含零依赖（Zero Dependency）**：输出的 Web Reader 网页将音频（Base64）、样式与高精度时间戳完全打包在单个 HTML 文件内，断网可用、可直接传输至手机/平板浏览器打开。
- **毫秒级卡拉OK逐句联动**：播放时段落平滑居中滚动，当前朗读的单句实时变色高亮；点击讲稿任意句子瞬间精准起播。
- **多音字双保险引擎**：提示词源头口语规避 + 专有词底层同音注音清洗，确保声音引擎发音标准，同时界面文字 100% 保持纯正学术规范。
- **全平台自适应交互**：PC 端支持空格快捷键与目录抽屉；移动端重构为大拇指分段切换器与居中大按键控制台，完美适配全面屏手势条并支持**锁屏控制与后台播放**。
- **段级 LLM 缓存与术语复利**：支持多级作用域术语覆盖，修改硬替换术语零 API 成本、立刻生效。

---

## 二、快速开始

### 1. 环境准备

本项目要求 **Python ≥ 3.10**，推荐在虚拟环境中安装依赖：

```bash
# 1. 克隆代码库
git clone https://github.com/Octahedron-BB/paper-zh.git
cd paper-zh

# 2. 安装 Python 运行时依赖
pip install -r requirements.txt
```

### 2. 配置 API 凭证

复制配置模板 `.env.example` 为 `.env`，填入 LLM 服务商密钥：

```ini
# 支持 deepseek（默认推荐）/ openai / gemini / 任意兼容端点
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-api-key-here
```

### 3. 一键运行命令

```bash
# 1) 将文献 PDF 放置在 papers/ 目录下（如 s41575-024-00932-1.pdf）

# 2) 全流程端到端执行（分段 -> 翻译 -> 讲稿 -> 对照 -> 语音 -> Web Reader）
python tools/run_pipeline.py --pdf s41575-024-00932-1

# 3) 批量自动处理 papers/ 下的所有 PDF 文献：
python tools/run_pipeline.py --all
```

#### 常用参数速查：

| 参数 | 示例 | 说明 |
| :--- | :--- | :--- |
| `--pdf` | `--pdf vieta2018` | 指定 PDF（支持文件名、doc_id 或绝对路径，自动补 `.pdf`） |
| `--all` | `--all` | 批量模式，自动循环处理 `papers/` 目录下的所有文献 |
| `--stage` | `--stage audio` | 单步运行指定阶段：`segment` / `translate` / `script` / `interleave` / `audio` / `reader` / `all` |
| `--limit` | `--limit 3` | 仅处理前 N 个段落（用于快速验证翻译与发音质量） |
| `--field` | `--field neuroscience` | 指定学科域，激活对应领域的专业术语表 |
| `--no-audio` | `--no-audio` | 纯文本模式，跳过语音合成与伴读网页打包 |
| `--voice` | `--voice zh-TW-HsiaoChenNeural` | 指定 TTS 声音模型（默认台湾晓臻，柔和自然） |
| `--rate` | `--rate +10%` | 语音朗读语速微调 |

---

## 三、目录结构

```text
paper-zh/
├─ README.md                  # 项目说明与使用指南
├─ requirements.txt           # 核心依赖清单 (pymupdf + pyyaml + edge-tts)
├─ .env.example               # 环境变量与 API 密钥模板
├─ glossary.yaml              # ★ 主术语表（跨文献复用的核心资产）
├─ glossary-d/                # ★ 单篇文献专属术语表 (<doc_id>.yaml)
├─ polyphone.yaml             # ★ 多音字与医学专有词发音清洗词典
│
├─ papers/                    # 输入目录：存放待处理 PDF 文献（git 忽略）
├─ data/                      # 产物输出目录（全部自动生成，git 忽略）
│   ├─ reader/<id>.html       # ★ 自包含双向伴读网页（双击即开）
│   ├─ audio/<id>.mp3         # ★ 完整播客音频 + 毫秒级时间戳 JSON + LRC/VTT
│   ├─ interleave/<id>.md     # 中英交错对照 Markdown（+ reader.css 样式）
│   ├─ translation/<id>.md    # 轨A 忠实学术全译
│   ├─ script/<id>.md         # 轨B 口语播客讲稿
│   ├─ segments/<id>.json     # 结构化段落分块数据
│   └─ cache/                 # 段落级 LLM 响应缓存
│
├─ tools/                     # 命令行工具入口
│   ├─ run_pipeline.py        # ★ 端到端主工作流入口
│   ├─ build_audio.py         # 语音合成与时间戳对齐工具
│   ├─ build_reader.py        # 自包含 Web Reader HTML 打包器
│   ├─ build_interleave.py    # 中英交错对照生成器
│   ├─ qa_report.py           # 自动化翻译与讲稿质量体检报告
│   └─ check_terms.py         # 术语命中与缩写冲突审计工具
│
├─ src/                       # 核心业务模块
│   ├─ polyphone.py           # 多音字发音清洗与正则转换
│   ├─ textnorm.py            # 中文排版规范化与数字千分位处理
│   ├─ prompts.py             # 提示词模板与版本控制器
│   ├─ segment.py             # PDF 版式分析与多栏提取算法
│   ├─ translate.py           # 轨A 翻译执行器
│   ├─ rewrite.py             # 轨B 讲稿重写执行器
│   └─ glossary.py            # 术语解析与作用域分发引擎
│
├─ devtools/                  # 开发者排错工具
│   └─ inspect_lines.py       # PDF 文本行级版式判定探针
│
└─ tests/                     # 离线自动化测试套件
    ├─ test_core.py           # 核心测试（术语表 / 缓存 / 多音字 / 缩写处理）
    └─ test_segment.py        # 分段不变量与结构完整性测试
```

---

## 四、产物矩阵与使用指南

| 产物路径 | 格式与类型 | 适用场景与推荐使用方式 |
| :--- | :--- | :--- |
| `data/reader/<doc_id>.html` | **自包含双向伴读网页** *(⭐推荐)* | **PC / 移动端浏览器直接打开**：内嵌完整音频、卡拉OK逐句高亮、点句即播、三视图切换、支持锁屏后台播放。 |
| `data/audio/<doc_id>.mp3` | **独立音频流** | 配合主流音频播放器使用，同目录配有 `.lrc` 与 `.vtt` 字幕。 |
| `data/interleave/<doc_id>.md` | **中英交错对照** | VS Code 打开按 `Ctrl+K V` / `Cmd+K V` 打开预览，通过大纲视图快速精读对照。 |
| `data/translation/<doc_id>.md` | **中文学术全译** | 逐段忠实翻译，适合快速查阅专业细节。 |
| `data/script/<doc_id>.md` | **中文口语讲稿** | 听觉友好的口语讲解文稿，去除了图表悬空指涉。 |

### Web Reader 伴读网页交互特性：
1. **三视图自由切换**：点击顶部切换器可在【中英对照】、【口语讲稿】与【忠实全译】之间无缝切换。
2. **逐句变色高亮**：在【口语讲稿】视图下，系统将自动跟踪播放进度，当前正在朗读的句子会高亮变色。
3. **点句即播（Seek on Click）**：鼠标或手指点击讲稿中的任意单句，播放器将瞬间跳转至该句起点播放。
4. **移动端后台保活**：基于 W3C `MediaSession API`，在 Android Chrome / iOS Safari 中切入后台或锁屏时，均可维持后台发声并通过系统锁屏面板控制进度。

---

## 五、配置与定制指南

### 1. 术语表体系与缓存机制

术语表是本系统跨文献沉淀的核心资产。系统将术语分为两类，其执行成本与处理逻辑截然不同：

- **`mode: hard_replace`（硬替换，默认推荐）**：
  翻译完成后由引擎进行确定性字符串替换。由于中文无曲折变化，此方式**零 API 消耗、修改后重跑即刻生效**。
- **`mode: prompt_hint`（上下文注入）**：
  直接注入 LLM 提示词中（用于解决语义歧义或需要重构句式的情况）。修改此类术语**仅会导致命中该词的特定段落重新翻译**。

#### 术语作用域优先级 (`scope`)：
```yaml
- term: MSN
  zh: 中型棘状神经元
  scope: field:neuroscience        # 学科域生效
- term: MSN
  zh: 内侧隔核
  scope: doc:s41583-025-00929-y    # 单篇文献专属覆盖（优先级最高）
```
> **解析规则**：优先级为 `doc` > `field` > `global`。同级若出现冲突将报错中断，避免静默混淆。

---

### 2. 多音字与专业发音清洗

针对医学和科技文献中常见的专有词读音错误（如“黏膜”误读为 *zhān*、“血栓栓塞”误读为 *sāi*、“校正”误读为 *xiào*），系统采用双层处理：

1. **源头提示词规避**：在生成讲稿阶段，自动将生硬的书面缩略句式转换为明确的口语表达（如“表现为”改写为“主要表现是”）。
2. **底层发音清洗字典 (`polyphone.yaml`)**：
   在调用声音合成引擎的底层内存流中，自动进行谐音替换（如将送往 TTS 的文字替换为“粘膜”、“栓色”、“矫正”）。

```yaml
# polyphone.yaml 示例
rules:
  - word: "黏膜"
    tts: "粘膜"
    note: "确保读 nián mó"
  - word: "血栓栓塞"
    tts: "血栓栓色"
    note: "确保塞读 sè"
```
> **核心保证**：网页展示、字幕和讲稿文字 **100% 保持专业医学书写**，仅底层音频引擎获得发音修正。

---

## 六、质量检验与测试

系统内置了全面的自动化质量检查与回归测试套件：

```bash
# 1. 运行六项质量体检（词比/讲稿保全率/未译残留/数字保真/术语落地/提示词泄漏）
python tools/qa_report.py

# 2. 运行离线单元测试套件（无需 API 密钥）
python tests/test_core.py       # 19/19 项测试：术语作用域、多音字映射、缩写清洗、段级缓存
python tests/test_segment.py    # 8/8 项测试：PDF 分段解析结构不变量
```

---

## 七、常见问题 (FAQ)

**Q：执行时报 `ModuleNotFoundError` 缺失依赖？**
请确保激活了正确的 Python 环境并安装了依赖：`pip install -r requirements.txt`。

**Q：为什么讲稿里完全没有“如表1所示/见图2”？**
这是预期设计。轨B（口语讲稿）面向听觉场景，听众无法实时查阅图表，因此系统在提示词层面已自动剥除图表指涉，确保讲解平滑完整。

**Q：修改了术语表或多音字表后如何重新生成？**
- 若修改了 `glossary.yaml` 中的 `hard_replace` 术语：直接运行 `python tools/run_pipeline.py --pdf <id> --stage translate`（0 API 开销）。
- 若修改了 `polyphone.yaml` 发音词典：直接运行 `python tools/run_pipeline.py --pdf <id> --stage audio` 重新合成音频。

---

## 八、排错与高级开发工具

当引入新期刊排版导致分段异常时，可使用内置的版式探针工具定位行级特征：

```bash
# 检查整篇文献的分段分布健康度
python tools/batch_segment.py

# 探针：打印指定 PDF 文本行的坐标、字号、主导字体与版式分类判定
python devtools/inspect_lines.py papers/xxx.pdf --page 4
python devtools/inspect_lines.py papers/xxx.pdf --grep "Anal cancer" --around 2
```

---

## 九、版权与数据安全说明

- **合规边界**：学术综述版权归原期刊与作者所有。本项目全套产物（译文、讲稿、音频、HTML 伴读）**仅供个人学习与研究使用**，严禁用于公开分发或商业用途。
- **Git 隔离防护**：项目 `.gitignore` 已配置严格规则，默认排除所有输入 PDF（`papers/*.pdf`）及所有生成数据（`data/`），防止版权敏感资产意外同步至公开代码仓库。

---

## 十、开源许可

本项目代码基于 [MIT License](LICENSE) 开源发布。
许可证仅适用于代码库本身的实现，不涵盖用户通过本工具处理的第三方文献及其派生产物。
