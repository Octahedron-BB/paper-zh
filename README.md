# 文献 → 中文分层伴读

把 Nature Reviews 之类的高密度英文综述 PDF，变成两样东西：

1. **轨A · 忠实全译**（`data/translation/`）—— 用来**看**，逐段对照原文
2. **轨B · 中文口语讲稿**（`data/script/`）—— 用来**听**，为后续配音准备

外加一份**中英交错对照文档**（`data/interleave/`），是做人工抽查时最顺手的形态。

> 仅个人自用。**不要**公开分发，也不要把译文/音频发到公开平台
> （原文多为订阅刊，条款禁止再分发）。

---

## 一、快速开始

> 文档里的命令都是**跨平台**的：路径一律用 `/`，命令用 `python`。
> Windows（PowerShell）和 macOS（zsh/bash）都能照抄。

### 0. 拿到代码

```bash
git clone https://github.com/Octahedron-BB/paper-zh.git
cd paper-zh
```

### 1. 准备 Python 环境

需要 **Python ≥ 3.10**，装两个依赖：

```bash
pip install -r requirements.txt        # pymupdf + pyyaml
```

建议用独立环境，别装进系统 Python：

```bash
conda create -n paper python=3.11 -y && conda activate paper
# 或者：python -m venv .venv && source .venv/bin/activate   （Windows: .venv\Scripts\activate）
```

后面的命令都假设**这个环境已经激活**（激活后 `python` 就指向它）。
如果你不想激活，也可以直接写解释器的完整路径，例如：
`"C:\path\to\envs\paper\python.exe" tools/run_pipeline.py ...`

### 2. 配置密钥

复制 `.env.example` 为 `.env`，至少填一个 key：

```
DEEPSEEK_API_KEY=sk-...
```

支持的供应商：`deepseek`（默认）/ `openai` / `gemini` / 任何 OpenAI 兼容服务。
`.env` 已被 git 忽略，**不要把 key 贴给别人或写进任何文档**。

### 3. 跑一篇新文献

```bash
# 1) 把 PDF 放进 papers/（文件名就是文档 ID，建议保留期刊编号，如 s41575-024-00932-1.pdf）
#    注意：仓库不含 PDF（版权原因），需要自己准备。

# 2) 跑流水线（分段 + 翻译 + 讲稿，一条命令到底）
python tools/run_pipeline.py --pdf s41575-024-00932-1 --stage all --workers 6

# 神经科学类文献要加 --field：带 field 作用域的术语**只有指定了它才生效**
# （首次指定后会记到 data/meta/，以后忘写也会自动沿用）
python tools/run_pipeline.py --pdf s41583-025-00929-y --field neuroscience --stage all --workers 6
```

`--pdf` 可以直接写**文件名或 doc_id**（自动去 `papers/` 找、自动补 `.pdf`），也可以写相对/绝对路径。

### 4. 生成中英对照文档

```bash
python tools/build_interleave.py --doc-id s41575-024-00932-1
```

---

## 二、目录结构

```text
<项目根目录>/
├─ README.md              ← 本文件
├─ requirements.txt       ← 依赖：pymupdf + pyyaml
├─ .env                   ← 你的密钥（git 忽略，自己维护）
├─ .env.example           ← 模板
├─ glossary.yaml          ← ★ 主术语表（跨文献复用的核心资产，手动编辑）
├─ glossary-d/            ← ★ 单篇术语覆盖，文件名 = <doc_id>.yaml
│
├─ papers/                ← ★ 输入：把 PDF 放这里（git 忽略）
├─ data/                  ← 产物（全部自动生成，git 忽略）
│   ├─ segments/<id>.json       分段结果（结构 + 每段原文）
│   ├─ translation/<id>.json/md 轨A 译文
│   ├─ script/<id>.json/md      轨B 讲稿
│   ├─ interleave/<id>.md       中英交错对照（+ reader.css 可选样式）
│   └─ cache/                   段级 LLM 缓存（删了会重新花钱）
│
├─ tools/                 ← 命令行入口
│   ├─ run_pipeline.py         主程序
│   ├─ build_interleave.py     生成中英对照
│   ├─ qa_report.py            六项自动体检
│   ├─ check_terms.py          缩写/同名异义审计（翻译前该跑）
│   └─ batch_segment.py        跨期刊分段健康检查
│
├─ devtools/              ← ★ 排错工具（换新期刊时用，详见第八节）
│   └─ inspect_lines.py        逐行打印「这行被判成什么了，为什么」
│
├─ tests/                 ← 离线测试（不需要密钥）
│   ├─ test_core.py            18 项：术语表 / 缓存 / 后处理
│   ├─ test_segment.py         8 项：分段结构不变量
│   └─ segment_baseline.json   分段基准数字
│
└─ archive/               ← 本地杂物（git 忽略）：日志、历史版本、一次性探针
```

---

## 三、产物怎么看

| 文件 | 用途 | 怎么看 |
|---|---|---|
| `data/interleave/<id>.md` | **中英对照**（推荐） | VS Code 打开 → `Ctrl+K V` / `Cmd+K V` 开侧边预览 → 用「大纲视图」跳章节 |
| `data/translation/<id>.md` | 纯中文译文 | 直接读；句子里的 `图2`/`表1` 是**悬空引用**（图表我们不做，属预期） |
| `data/script/<id>.md` | 中文口语讲稿 | 这是**给耳朵**的稿子，读起来会比译文啰嗦，正常 |
| `data/*/<id>.json` | 结构化数据 | 音频定位/工具用，不用手看 |

关于对照文档的**样式**（可选项）：把英文压灰压小，读中文时几乎不干扰视线。
仓库里已经带了 `.vscode/settings.json`，**clone 下来开箱即用**；
如果你的编辑器没生效，手动在自己的 `settings.json` 里加一行即可
（VS Code 支持相对工作区根的路径，所以不必写死绝对路径）：

```json
"markdown.styles": ["data/interleave/reader.css"]
```

---

## 四、哪些地方可以手动调整

| 想改什么 | 改哪里 | 代价 |
|---|---|---|
| **某个术语的中文译名** | `glossary.yaml` | **零成本**（见下方说明） |
| 某篇文献里的特殊含义 | `glossary-d\<doc_id>.yaml` | 零成本或只重译命中段 |
| 讲稿的语气/口语程度 | `src/prompts.py` 的 `SCRIPT_SYSTEM` | **递增 `SCRIPT_VERSION` → 全部重跑** |
| 翻译的语体/规则 | `src/prompts.py` 的 `TRANSLATE_SYSTEM` | 递增 `TRANSLATE_VERSION` → 全部重译 |
| 数字格式、去重复词等 | `src/textnorm.py` | **零成本**（不进缓存） |
| 版式识别阈值（换期刊时） | `src/segment.py` 顶部常量 | 递增 `SEGMENTER_VERSION`，分段会变 |
| 一次处理哪些段 | `run_pipeline.py --limit N` / `--only <sid>` | 少花钱，适合试水 |

### ⭐ 术语表：理解这一点能省很多钱

术语分两类，**成本完全不同**：

- `mode: hard_replace`（默认）——译文生成后**做字符串替换**。
  中文没有性/数/格变化，换词近乎无损，所以**改它 0 次 API、立刻生效**。
  实例：`retrieval stopping -> 检索停止`
- `mode: prompt_hint` ——必须进提示词（歧义澄清、要改句结构）。
  改它**只重译真正命中该术语的段落**。

**原则：能用字符串替换解决的，绝不调 LLM。**
所以遇到译名不满意，先试着加/改一条 `hard_replace`，而不是急着重跑。

术语表的**作用域**（同名异义就靠它）：

```yaml
- term: MSN
  zh: 中型棘状神经元
  scope: field:neuroscience        # 只在神经科学域生效
- term: MSN
  zh: 内侧隔核
  scope: doc:s41583-025-00929-y    # 只在这一篇生效（优先级最高）
```

优先级 `doc` > `field` > `global`；同级出现两种译法会**直接报错中止**，不会静默挑一个。

### ⚠️ 版本号是与缓存绑定的

`src/prompts.py` 的 `*_VERSION` 和 `src/segment.py` 的 `SEGMENTER_VERSION`
都是**缓存键的一部分**。改了规则却不递增版本号 → 缓存会把旧结果当成有效的继续用
（**静默不生效**，最难发现的一类 bug）。改了代码觉得"怎么没变化"，先查这里。

---

## 五、质量检查

```bash
# 六项体检：译文完整性 / 讲稿保全率 / 未翻译残留 / 数字保真 / 术语落地 / 提示词泄漏
python tools/qa_report.py

# 离线测试（不花钱、不需要密钥）
python tests/test_core.py
python tests/test_segment.py

# 跨期刊分段体检（新加期刊时先跑这个）
python tools/batch_segment.py

# 翻译**之前**的缩写/同名异义审计（新领域必跑）
python tools/check_terms.py --doc-id <doc_id>
```

`test_segment.py` 需要 `papers/` 里有对应 PDF；没有就自动跳过（会打印「可用样本」），
所以**别人 clone 下来不装 PDF 也能跑通**。

**目前状态**：4 篇文献（62 / 109 / 37 / 53 段）全部完成，0 失败；
体检各项达标；测试 `test_core.py` 18/18、`test_segment.py` 8/8。

**成本参考**：一篇 1.2 万词的综述，全篇翻译约 **0.16 元**量级。
所以"省 token"不是做段落缓存的理由 —— 段级缓存真正保护的是
**你人工校订过的成果**（钱买不到）和**术语一致性**。

---

## 六、常见问题

**Q：报 `ModuleNotFoundError: No module named 'pymupdf'`？**
没装依赖，或者 `python` 指向了别的环境。先 `pip install -r requirements.txt`，
再确认 `python -c "import pymupdf; print(pymupdf.__version__)"` 有输出。

**Q：终端里中文全是乱码（Windows）？**
PowerShell 的老问题，**不要用 `>` 重定向看中文输出**。用：
`... | Out-File -FilePath out.txt -Encoding utf8; Get-Content out.txt -Encoding utf8`
（macOS 的 bash/zsh 默认 UTF-8，没有这个问题。）

**Q：长命令在 PowerShell 里执行不了 / 被吃掉？**
Windows PowerShell 对多行和超长命令不稳定（PSReadLine 的已知毛病）。
写成脚本文件跑，或拆成短命令。

**Q：改了术语表，译文没变化？**
看你改的是哪一类。`hard_replace` 立刻生效（重跑一次让它重新做后处理即可，0 次 API）；
`prompt_hint` 要重跑命中段。

**Q：为什么产物里说"见表1/图2"，却没有表1图2？**
**这是预期行为**：图表和 Box 一律不处理。轨A 只用来对照原文看，看懂即可；
轨B（讲稿）里的图表指涉已经在提示词层面清掉了（否则听的人无从查证）。

**Q：能不能把多篇文献的译文合成一本书？**
可以，`data/translation/*.md` 直接拼；但注意 sid 锚点要保留（音频定位依赖它）。

---

## 七、已知问题 / 还没做

未做：**TTS**（配音）与段落时间戳。这是最后一层，不影响上面任何缓存，
随时可以加；讲稿已经为它准备好了。

已知的小问题（都不影响阅读，诚实列出）：

1. `data\script\` 里有极少数句子残留图表指涉（4 篇里 1 处）。
2. 段级缓存键里**没有章节名**，而讲稿提示词里有「所在章节」。
   影响极小（译文完全相同的段落才会撞），但属于"键没覆盖输入"的隐患。
3. 有一段（s41575，4 段）在修标题时被移除，我验证了总词数在基准 ±3% 内，
   **但没有逐段确认**它们都是图注片段。若要严谨，值得人工扫一眼。

---

## 八、调试脚本怎么放（`devtools/` 与 `archive/`）

调试期积累了很多脚本。**“要不要上传”不该按“是不是调试用的”来分，
而该按“换台电脑还需不需要它”来分**：

| 类别 | 放哪 | 上传？ | 为什么 |
|---|---|---|---|
| **可复用的排错工具** | `devtools/` | ✅ | 换新期刊/换设备真的会再用 |
| 一次性输出日志（`*.txt`） | `archive/` | ❌ | 它是“上次运行的输出”，不是资产；要看重新跑一条命令就有 |
| 只针对某一篇的探针、历史版本（`segment_v1..v5.py`） | `archive/` | ❌ | 没有复用价值；演进的**理由**已经写在笔记里，代码本身留本地就够 |

`archive/` 已在 `.gitignore` 里，所以**本地的杂物不会跟着上传**，
而 `devtools/` 会跟着走 —— 这样“跨设备调试方便”和“仓库干净”两件事就不冲突了，
**不需要开第二个仓库，也不需要搞分支**。

### `devtools/inspect_lines.py`：换新期刊时的第一把工具

换一篇新期刊发现分段不对时，标准动作是：

```bash
# 1) 先看整体健康度（会报“段落数偏少/最长段过大/标题数过少”）
python tools/batch_segment.py

# 2) 定位出问题的那一行，看它被判成了什么、为什么
python devtools/inspect_lines.py papers/xxx.pdf --grep "Anal cancer" --around 2
python devtools/inspect_lines.py papers/xxx.pdf --page 4
python devtools/inspect_lines.py papers/xxx.pdf --kind runin,h1,h2
```

它会打印每行的：页码 / 栏 / y / x0 / 字号 / **主导字体** / **判定 kind**，
以及是否落在矩形里（`R`）因而被当 region 排除（`X`）。
拿着这些字段对照 `src/segment.py` 的 `_classify()`，就知道是哪条规则判错了。

补充说明：调试期写过 40 多个探针脚本（在 `archive/scratch/`），
但它们几乎都只针对某一篇 PDF 的某个具体问题，换一篇就没用了。
真正反复用到的能力只有一个 ——“这一行文字被当成什么了？为什么？”，
所以只把这一件事固化成了工具，其余留在本地不上传。

---

## 九、上传到 GitHub 前必须知道的事

### ⚠️ 版权：不要把"产物"传上去

这个工具会**把你的全文翻译写进 `data/translation/`、`data/script/`**。
Nature Reviews 这类期刊多为订阅刊，条款明确禁止再分发。
**把整篇中文译文推到公开仓库，属于"向公众提供"，和我们自己定的红线直接冲突。**

所以 `.gitignore` 里已经把下面这些全部排除了：

| 不提交 | 原因 |
|---|---|
| `papers/*.pdf` | 原文版权 |
| `data/translation/`、`data/script/` | **全文译文/讲稿，版权风险最高** |
| `data/segments/`、`data/interleave/` | 派生自原文 |
| `data/cache/` | LLM 缓存，且体积不可控 |
| `archive/`、`.brainstorm-notes/` | 私人开发记录 |
| `.env` | 密钥 |

**仓库里保留的是工具本身**：`src/`、`tools/`、`tests/`、术语表、README。
这才是可分享、可复现、无版权风险的部分。

### 建议仓库带上的东西

- `requirements.txt` ✅（已带）
- `.vscode/settings.json` ✅（已带，让对照文档的样式开箱即用）
- `LICENSE` ✅（已带 MIT，见第十节）
- 仓库描述里写一句「工具，不含任何论文原文或译文」

### 提交前自查

```bash
# 确认该忽略的都没被跟踪（应该看不到 .env / papers/ / data/）
git status --short
git ls-files | grep -E 'data/|papers/|\.env'   # 应无输出
```

---

## 十、许可

**MIT**（见 `LICENSE`）。**但请注意许可范围。**

MIT 只覆盖**本仓库里的代码**。它**不覆盖**你用本工具生成的内容 ——
译文、讲稿、对照文档、以后可能有的音频。那些东西源自第三方受版权保护的论文，
能不能分发、发给谁，由论文权利人与你的使用场景决定。

换句话说：**代码可自由使用，产物要自己把握。**

