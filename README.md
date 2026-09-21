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
- [七、文献速览（可选模块）](#七文献速览可选模块)
- [八、常见问题 (FAQ)](#八常见问题-faq)
- [九、排错与高级开发工具](#九排错与高级开发工具)
- [十、版权与数据安全说明](#十版权与数据安全说明)
- [十一、开源许可](#十一开源许可)

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
├─ examples/                  # ★ 范例产物（包含间歇性禁食文献的交互网页与完整音频）
│   ├─ README.md              # 范例说明文档
│   └─ s41574-022-00638-x/    # 42.7分钟伴读网页与音频示例
│
├─ papers/                    # 输入目录：存放待处理 PDF 文献（git 忽略）
│   └─ inbox/                 # 文献速览用：手工下载的 PDF 先丢这里（自动认领，待实现）
├─ data/                      # 产物输出目录（全部自动生成，git 忽略）
│   ├─ reader/<id>.html       # ★ 自包含双向伴读网页（双击即开）
│   ├─ audio/<id>.mp3         # ★ 完整播客音频 + 毫秒级时间戳 JSON + LRC/VTT
│   ├─ interleave/<id>.md     # 中英交错对照 Markdown（+ reader.css 样式）
│   ├─ translation/<id>.md    # 轨A 忠实学术全译
│   ├─ script/<id>.md         # 轨B 口语播客讲稿
│   ├─ segments/<id>.json     # 结构化段落分块数据
│   ├─ feed/                  # 文献速览：items.json 状态库 + digest/ 每期快照 + 提要有缓存
│   └─ cache/                 # 段落级 LLM 响应缓存
│
├─ tools/                     # 命令行工具入口
│   ├─ run_pipeline.py        # ★ 端到端主工作流入口
│   ├─ build_digest.py        # ★ 文献速览：PubMed 检索 → 两级提要 → 手机 HTML/MD
│   ├─ push_digest.py         # ★ 文献速览：把某一期推送到微信 / Telegram / Discord
│   ├─ build_audio.py         # 语音合成与时间戳对齐工具
│   ├─ build_reader.py        # 自包含 Web Reader HTML 打包器
│   ├─ build_interleave.py    # 中英交错对照生成器
│   ├─ qa_report.py           # 自动化翻译与讲稿质量体检报告
│   ├─ check_terms.py         # 术语命中与缩写冲突审计工具
│   ├─ disambiguate.py        # 同名异义缩写消歧（把提议写入 glossary-d/）
│   └─ batch_segment.py       # 批量分段健康度检查
│
├─ src/                       # 核心业务模块
│   ├─ docs.py                # ★ 文档自动发现（papers/ 与各产物目录里有哪些文献）
│   ├─ feed.py                # 文献速览：PubMed 增量检索与状态库
│   ├─ push.py                # 推送渠道（PushPlus / Telegram / Discord）
│   ├─ runlog.py              # 工具自记日志（定时任务无需 shell 重定向）
│   ├─ model.py               # 文档/节/段数据结构与 slug（节路径）规则
│   ├─ segment.py             # PDF 版式分析与多栏提取算法
│   ├─ translate.py           # 轨A 翻译执行器
│   ├─ rewrite.py             # 轨B 讲稿重写执行器
│   ├─ glossary.py            # 术语解析与作用域分发引擎
│   ├─ abbrev.py              # 缩写抽取、定义识别与同名异义检测
│   ├─ polyphone.py           # 多音字发音清洗与正则转换
│   ├─ textnorm.py            # 中文排版规范化与数字千分位处理
│   ├─ prompts.py             # 提示词模板与版本控制器
│   ├─ providers.py           # LLM 供应商抽象（仅用标准库 urllib，零 SDK 依赖）
│   └─ cache.py               # 段级缓存键与存取
│
├─ devtools/                  # 开发者排错工具
│   ├─ inspect_lines.py       # PDF 文本行级版式判定探针
│   ├─ audit_hard_landing.py  # hard_replace 术语到底有没有落地（打印替代写法证据）
│   └─ audit_term_density.py  # hard_replace 译名是否把译文“刷”得太啰嗦
│
└─ tests/                     # 离线自动化测试套件（样本自动发现）
    ├─ test_core.py           # 核心测试（术语表 / 缓存 / 多音字 / 缩写处理）
    ├─ test_digest.py         # 文献速览测试（快照选取 / 计长口径 / doc_id 推导）
    ├─ test_push.py           # 推送层测试（渠道选择 / 分片边界 / 不泄漏密钥）
    ├─ test_segment.py        # 分段不变量、节路径（slug）规范
    └─ segment_baseline.json  # 分段基准数字（用 test_segment.py --update 刷新）
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

> **写 `aliases` 的规则：别名必须是完整词组，不要用短子串。**
> 别名是确定性字符串替换，子串会连带误伤包含它的其它词，**而且不会报错** ——
> 例如用「菌群」作 `microbiome` 的别名，会一并破坏「细菌群落」
> （bacterial community，另一个概念）。拿不准就写整段词组。
>
> **模式选择规则：能用 `hard_replace` 解决的，绝不调 LLM。**
> `hard_replace` 零成本、改完立即生效；`prompt_hint` 会让命中该词的段落重译。
> 因此只有“必须指导模型怎么写”的才用 `prompt_hint` ——
> 典型是缩略语的首次出现格式、以及需要彼此区分的近义术语。

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
python tools/qa_report.py                    # 默认体检全部已翻译文献
python tools/qa_report.py --doc vieta2018    # 只看指定文献

# 2. 运行离线单元测试套件（无需 API 密钥）
python tests/test_core.py       # 术语作用域、多音字映射、缩写清洗、段级缓存
python tests/test_segment.py    # PDF 分段结构不变量、节路径（slug）规范
python tests/test_digest.py     # 快照选取、提要计长口径、doc_id 推导
python tests/test_push.py       # 渠道选择、分片边界、密钥不泄露
```

**测试样本与体检对象都是自动发现的**：`test_segment.py` 扫 `papers/*.pdf`，
`qa_report.py` 扫 `data/translation/`，两处共用 `src/docs.py`。
因此**新丢一篇 PDF 进去就会被自动纳入，不需要维护任何清单**。

`test_segment.py` 会与 `tests/segment_baseline.json` 里的基准数字比对，
新增 PDF 或改动分段逻辑后基准会不匹配：

```bash
python tests/test_segment.py --update    # 刷新基准（仅在确认改动是你想要的之后）
```

> ℹ️ **分段器的已知局限**：期刊标题若因排版折成两行，分段器目前**只取末行**，
> 标题会被截断（表现为标题以小写单词开头）。
> `test_segment.py::test_headings_are_not_truncated` 专盯此类问题。

---

## 七、文献速览（可选模块）

本模块独立于上述 PDF 处理流水线，解决的是**流水线之前**的一步：从 PubMed 增量检索
Nature Reviews 系列的新文献，生成中文提要与移动端页面，并可推送到微信 / Telegram / Discord。

### 1. 过滤策略（基于实测）

`"Nat Rev*"[jour]` 的检索结果中混有大量非综述条目。实测近 90 天共 566 条：

| 指标 | 实测值 |
|---|---|
| 一周产量 | 约 **44 条**（覆盖 18 个期刊） |
| 带摘要比例 | **39%**（566 条中 209 条） |
| 「有摘要」与「带 `Review` 标签」重合度 | **98%**（204 / 209） |

无摘要的 61% 为 Research Highlight、News 与更正启事。因此以「仅保留带摘要的条目」
作为过滤条件，可将约 44 条/周降至约 16 条/周。该条件与 `Review` 出版类型标注近乎等价，
但无需依赖期刊端的标注质量。

### 2. 两级提要

| 字段 | 长度 | 用途 |
|---|---|---|
| `brief` | ≤ 25 字 | 摘要式浏览；推送通知正文 |
| `detail` | 50–85 字 | 展开阅读，含机制 / 数据 / 分类框架 |

早期版本要求模型输出单一「20–45 字」字段，实测 8 条中 7 条超长（57–88 字）。
原因不在约束强度，而在于**模型倾向写入更多信息**。现改为提供两个独立字段：
模型可将完整信息写入 `detail`，同时必须另给一句独立的短句，两者互不依赖。
`brief` 实测中位数为 25 字。

### 3. 用法

```bash
# 1) 增量拉取 + 生成提要 + 产出手机页面（首次可用 --days 60 回填）
python tools/build_digest.py --days 30

# 2) 试水：只推 4 条（省 token）
python tools/build_digest.py --limit 4

# 3) 只看体量、不调用任何 LLM（零成本），并复核过滤器没误杀综述
python tools/build_digest.py --no-llm --show-dropped

# 4) 终端重看最近一期 / 重新渲染（改样式零成本）
python tools/build_digest.py --list
python tools/build_digest.py --render-only

# 5) 挑中第 3、7 条 → 打印出确切命令
python tools/build_digest.py --pick 3 7
```

产出在 `data/feed/digest/<日期>.html`——**单文件自包含、无外部依赖**，
可以直接 AirDrop 到手机或用浏览器打开。默认只显示 `brief`，点卡片标记「要读」，
底部汇总编号，点「复制编号」即可拿到 `--pick` 要的参数。

### 4. 推送渠道

支持微信（PushPlus）、Telegram、Discord 三个渠道，可单选亦可多选。

```bash
python tools/push_digest.py --list-channels             # 查看各渠道配置状态
python tools/push_digest.py --channels all --dry-run    # 预览内容，不实际发送
python tools/push_digest.py --channels telegram         # 单选
python tools/push_digest.py --channels telegram,discord # 多选
python tools/push_digest.py --channels all              # 所有已配置的渠道
```

也可在生成时直接推送：`python tools/build_digest.py --days 30 --push wechat`。
仅需重发某一期而不重新检索、不调用 LLM：`python tools/push_digest.py --channels wechat --days 7`。

| 渠道 | 所需 `.env` 变量 |
|---|---|
| `wechat` | `PUSHPLUS_TOKEN`（可选 `PUSHPLUS_TOPIC` 群组编码） |
| `telegram` | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| `discord` | `DISCORD_WEBHOOK_URL`，或 `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID` |

`--channels all` 仅发送**配置完整**的渠道；未配置的渠道会在输出中说明跳过原因。

**实现说明**

1. **只推内容，不推链接。** 速览页面与 Web Reader 均为单文件自包含 HTML，**没有 URL**，
   链接在手机上无法打开。三个渠道均可直接承载正文，故发送正文。
2. **所有渠道统一发送纯文本。** Telegram 的 MarkdownV2 要求转义
   ``_*[]()~`>#+-=|{}.!``，遗漏一个字符即导致整条发送失败；Discord 使用自有 Markdown
   方言；PushPlus 使用 md 模板 —— 三者规则互不兼容。统一纯文本可从根源上消除此类问题。
3. **微信渠道限制单条消息。** `src/push.py` 的 `POLICY` 中微信 `max_messages=1`，
   条目超出容量时只发送首条，并**明确说明剩余条数**；Telegram / Discord 不受此限。

**故障处理**：单个渠道失败不影响其他渠道，结果逐条列出；配置缺失时报告的是**变量名**，
而非难以理解的 HTTP 401。**输出中不会出现密钥的值。**

**`--days` 语义**：`--days` 是**检索回看窗口**，不是推送范围。推送范围由本地状态库决定——
只推送状态为 `new`、即从未推送过的条目（记录于 `data/feed/items.json`）。
因此定期任务建议使用较大的窗口（如 `--days 30`）：若某次未执行，下次仍可补回遗漏；
状态库保证不会重复推送。窗口设为 `7` 则会在漏跑时永久遗漏中间数日。

### 5. 微信详情页排版

PushPlus 的微信推送分两层，**只有第二层可自定义**：

| 层 | 内容 | 是否可控 |
|---|---|---|
| ① 对话列表中的卡片 | 标题 + 摘要 + 链接 | ❌ 使用微信模板消息，字段经微信审核，不可自定义 |
| ② 点开后的详情页 | 请求的 `content` | ✅ 由 `template` 参数决定渲染方式 |

详情页默认输出结构化排版：序号 + **标题** / 简介 / `detail` / 期刊·日期·**可点击 DOI**。
`--style brief` 可省掉 `detail`（条目较多、需要省容量时使用）。
样式有两种挂载方式，由 `.env` 的 `PUSHPLUS_TEMPLATE` 选择：

| 值 | 样式挂载方式 | 说明 |
|---|---|---|
| `html`（默认） | `<style>` 块 + class | markup 约省四成，容量接近翻倍 |
| `html-inline` | 逐元素内联 `style` | 已验证可用，作为保底方案 |
| `markdown` / `txt` | 纯文本 | 不使用 HTML |

微信渠道内容上限为 **2 万字**（免费额度）。实测容量（带 `detail`）：

| 条数 | `html`（`<style>` 块） | `html-inline`（内联） |
|---|---|---|
| 11 条 | 5,671 字（30%） | 7,948 字（42%） |
| 25 条 | 11,551 字（61%） | 17,342 字（91%） |
| 40 条 | **18,019 字（95%），可容纳** | 超出上限 |

内容超出上限时按**条目边界**截断，并在末尾说明未显示的条数。

### 6. 与 PDF 流水线的衔接

**手工获取 PDF 的环节不做自动化**（例如通过校园网下载）。工具的作用是**在断点两侧各备好落点**：

`doc_id` 完全由 DOI 决定（`10.1038/s41583-025-00929-y` → `s41583-025-00929-y`），
与 `run_pipeline.py` 的 `doc_id = pdf.stem` 规则一致；PubMed 题录的 DOI 覆盖率为 **100%**。
因此在尚未下载 PDF 时，`--pick` 即可给出完整命令：

```text
PDF 存成 : s41583-025-00929-y.pdf  ->  放进 papers/
运行     : python tools/run_pipeline.py s41583-025-00929-y --field neuroscience --stage all
```

`--field` 由刊名自动推导（`Nature reviews. Neuroscience` → `neuroscience`），
避免因漏传 `--field` 导致 `field:` 级术语**静默**少命中。

### 7. 缓存与术语

速览提要有独立缓存，其键**不含术语**：提要在生成之后才做 `hard_replace` 字符串替换，
因此**修改术语 = 0 条失效、立即生效**，与轨A / 轨B 对 `hard_replace` 的承诺一致。
代价是**提示词中不能包含术语块** —— 否则等于将术语间接写入缓存键，该设计即失效。

### 8. 已修正的问题（均有回归测试）

| 问题 | 症状 | 修正 |
|---|---|---|
| 快照按文件名取最新 | `-`(0x2D) < `.`(0x2E)，`2026-09-21-0843.json` 排在 `2026-09-21.json` 之前，取末尾反而拿到旧的一期 | 改为按快照内部 `generated_at` 排序 |
| 同一日期重复运行覆盖快照 | 已发到手机的页面与最新快照编号不一致，`--pick` 指向错误文献 | 文件名追加时刻（`2026-09-21-0843`） |
| 用 `len()` 判断中文长度 | `BRCA1-BARD1 与 53BP1 轴拮抗决定 HR 或 NHEJ 的选择。` 的 `len()` 为 40，实读 15 字，被误判超长 | 统一使用 `textnorm.reading_len()`（连续拉丁串计 1 字） |
| 详情页元信息行整体转义 | `<a>` 标签被转义为文字，页面直接显示标签源码 | 逐段转义后再拼接 |

---

## 八、常见问题 (FAQ)

**Q：执行时报 `ModuleNotFoundError` 缺失依赖？**
请确保激活了正确的 Python 环境并安装了依赖：`pip install -r requirements.txt`。

**Q：为什么讲稿里完全没有“如表1所示/见图2”？**
这是预期设计。轨B（口语讲稿）面向听觉场景，听众无法实时查阅图表，因此系统在提示词层面已自动剥除图表指涉，确保讲解平滑完整。

**Q：修改了术语表或多音字表后如何重新生成？**
- 若修改了 `glossary.yaml` 中的 `hard_replace` 术语：直接运行 `python tools/run_pipeline.py --pdf <id> --stage translate`（0 API 开销）。
- 若修改了 `polyphone.yaml` 发音词典：直接运行 `python tools/run_pipeline.py --pdf <id> --stage audio` 重新合成音频。

**Q：`--doc-id` / `--pdf` 必须传吗？**
`papers/` 下只有一篇文献时可以省略，工具会自动选中它；有多篇时**必须显式指定**，
否则会报错并列出全部候选。漏传或传错都不会静默跑错文档 —— 工具宁可报错，也不会猜。
候选文献与学科域由 `src/docs.py` 统一发现（`papers/` 下的 PDF、各产物目录里的 doc_id、
`data/meta/<doc_id>.json` 里的 field），无需维护任何清单。

---

## 九、排错与高级开发工具

当引入新期刊排版导致分段异常时，可使用内置的版式探针工具定位行级特征：

```bash
# 检查整篇文献的分段分布健康度
python tools/batch_segment.py

# 探针：打印指定 PDF 文本行的坐标、字号、主导字体与版式分类判定
python devtools/inspect_lines.py papers/xxx.pdf --page 4
python devtools/inspect_lines.py papers/xxx.pdf --grep "Anal cancer" --around 2
```

---

## 十、版权与数据安全说明

- **合规边界**：学术综述版权归原期刊与作者所有。本项目全套产物（译文、讲稿、音频、HTML 伴读）**仅供个人学习与研究使用**，严禁用于公开分发或商业用途。
- **Git 隔离防护**：项目 `.gitignore` 已配置严格规则，默认排除所有输入 PDF（`papers/*.pdf`）及所有生成数据（`data/`），防止版权敏感资产意外同步至公开代码仓库。

---

## 十一、开源许可

本项目代码基于 [MIT License](LICENSE) 开源发布。
许可证仅适用于代码库本身的实现，不涵盖用户通过本工具处理的第三方文献及其派生产物。
