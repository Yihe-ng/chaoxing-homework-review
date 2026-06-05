# 超星学习通作业导出解析助手

> 采集超星学习通已完成作业，AI 生成逐题解析，输出 Word + Markdown 复习资料。

<!-- README-I18N:START -->
**中文** | [English](./README.en.md)
<!-- README-I18N:END -->

从超星学习通导出已完成作业，调用 DeepSeek API 生成逐题解析，最终输出为适合复习背诵的 Word 和 Markdown 文档。

两阶段流水线：

```
采集                                    复习
Playwright 手动登录                     读取 raw JSON
  ↓                                       ↓
requests 复用登录态爬取                  去重、合并、清洗题目
  ↓                                       ↓
交互式选课 → 选作业 → 导出 JSON          DeepSeek API 生成解析
                                          ↓
                                        DOCX + Markdown + 复核清单
```

> **安全边界**：本工具不自动登录、不自动答题、不绕过访问限制、不提交任何内容。只读取你有权限访问的页面。

## 环境配置

**安装 uv**（如未安装）：[uv 安装指南](https://uv.doczh.com/getting-started/installation/)

安装项目依赖：

```powershell
uv sync
```

浏览器说明：Playwright 会优先使用系统自带的 Microsoft Edge，无需额外安装。如果系统没有 Edge 或 Chrome，才需要运行：

```powershell
uv run playwright install chromium
```

**获取 API 密钥**：本项目默认使用 [DeepSeek](https://platform.deepseek.com/)（注册后在 [API Keys](https://platform.deepseek.com/api_keys) 页面创建密钥）。同时也兼容所有 OpenAI Chat Completions API 格式的提供商（如 OpenAI、Groq、硅基流动等），只需修改 `.env` 中的 `AI_BASE_URL` 和 `AI_MODEL` 即可。

**配置 `.env`**：将 `.env.example` 重命名为 `.env`，然后编辑填入你的密钥：

```text
AI_API_KEY=你的 API 密钥
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-flash
AI_MAX_TOKENS=2000
AI_VISION_ENABLED=false
AI_VISION_MAX_IMAGES=4
DOCX_FONT=Microsoft YaHei
```

设 `AI_API_KEY` 即可。也兼容 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`。
当 `AI_VISION_ENABLED=false` 时，程序无法识别包含图片的题目；请开启并将 `AI_MODEL` 改为支持视觉识别的模型，以便正常处理带图片的题目。

`CHAOXING_*` 等采集相关变量都有内置默认值，无需在 `.env` 中设置，详见[配置参考](#配置参考)。

**交给 AI 助手配置：** 将以下内容复制粘贴给 Claude Code、Cursor、Cline 等 AI 编程工具，Agent 会先检测当前环境、汇总报告，等你确认后再执行安装：

```text
按照 https://raw.githubusercontent.com/Yihe-ng/chaoxing-homework-review/main/skills/homework-review/SKILL.md 中的说明，帮我安装并配置这个项目。
```

## 使用方法

### 交互式采集（主要方式）

一键启动，按提示操作即可：

```powershell
uv run main.py
```

**操作流程：**

1. **登录** — 工具自动打开浏览器跳转到学习通页面。在浏览器中完成登录（支持扫码、手机号、学校统一认证等方式），然后回到终端按 Enter。
2. **选课** — 输入课程关键词过滤（如 `计组`），勾选需要采集的课程。
3. **选作业** — 默认勾选所有"已完成"作业，确认即可。
4. **采集** — 工具自动爬取每份作业的题目、选项、答案和得分，保存为 JSON。
5. **生成复习资料** — 采集完成后会询问是否立即生成复习资料。
   默认只处理本轮选择并成功采集的作业，不会自动把 `raw/` 中历史
   采集的其他章节混入。确认后调用 DeepSeek API 为每道题生成解析，
   最终输出 Word 和 Markdown 文档。

登录态会保存在 `.local/chaoxing_state.json`，下次运行无需重新登录。如果登录过期，重新运行 `uv run main.py` 并在浏览器中再次登录即可。

**常用参数：**

| 参数 | 作用 |
|------|------|
| `--course "计算机组成与结构"` | 跳过选课交互，直接匹配课程（可重复使用） |
| `--yes` | 跳过所有交互确认，使用默认选项 |
| `--no-review` | 只采集 JSON，不生成复习资料 |
| `--review-all` | 生成复习资料时读取当前课程 `raw/` 下全部 JSON |
| `--verify-answers` | 启用 AI 答案校验，标记可能出错的答案 |
| `--output-dir "my-output"` | 指定输出目录（默认 `output`） |

**示例：**

```powershell
# 指定课程 + 跳过交互 + 启用答案校验
uv run main.py --course "计算机组成与结构" --yes --verify-answers

# 只采集不复习
uv run main.py --course "人工智能基础" --no-review

# 采集后对该课程 raw 目录下全部作业生成复习资料
uv run main.py --course "人工智能基础" --review-all
```

### 从已有 JSON 生成复习资料

如果已经有 JSON 文件（手动导出或之前的采集结果），可以直接生成复习资料。

先试运行（dry-run），不调用 API，快速检查输入是否正确：

```powershell
uv run homework-review "output/人工智能基础/raw" --dry-run --output-dir "output/人工智能基础/review"
```

确认无误后，正式调用 API 生成解析：

```powershell
uv run homework-review "output/人工智能基础/raw" --output-dir "output/人工智能基础/review" --verify-answers
```

**参数：**

| 参数 | 作用 |
|------|------|
| `--dry-run` | 不调用 API，生成占位解析（用于快速检查） |
| `--verify-answers` | 让模型独立校验导出答案，标记风险题目 |
| `--limit N` | 只处理前 N 道题（测试用） |
| `--title "复习资料"` | 自定义文档标题 |
| `--output-dir "path"` | 输出目录 |
| `--cache "path"` | 解析缓存文件路径 |

## 输出说明

采集和复习的输出目录结构：

```text
output/
  计算机组成与结构/
    raw/                              # 采集的原始 JSON
      第一章作业.json
      第三章 总线作业.json
    review/                           # 复习资料
      计算机组成与结构-第一章_第三章-复习资料.docx
      计算机组成与结构-第一章_第三章-复习资料.md
      计算机组成与结构-第一章_第三章-复习资料-复核清单.md
      questions.enriched.json         # 增强版 JSON（含解析）
      explanations.cache.json         # 解析缓存（下次运行复用，节省 API 费用）
```

`raw/` 会持续保存历史采集的 JSON。交互式采集后立即生成复习资料时，
默认只使用本轮选中的作业文件；如果需要把 `raw/` 下全部历史作业一起
生成，请使用 `--review-all`，或单独运行 `homework-review` 并把
`raw/` 目录作为输入。

交互式采集生成的复习资料会按本轮选择自动命名，例如：

- 选择连续章节：`计算机组成与结构-第一至二章-复习资料.docx`
- 选择非连续章节：`计算机组成与结构-第一章_第三章-复习资料.docx`
- 选择普通作业：`人工智能基础-混合智能_行为智能_第一次_第二次作业-复习资料.docx`
- 使用 `--review-all`：`人工智能基础-完整复习资料.docx`

如果同名文件已经存在，会自动追加 `-2`、`-3` 等后缀，Word、Markdown
和复核清单会使用同一个文件名前缀，避免后续生成覆盖前一次结果。

**各文件说明：**

| 文件 | 说明 |
|------|------|
| `.docx` | 排版完整的 Word 复习文档，适合打印或在 WPS/Word 中阅读 |
| `.md` | Markdown 格式，适合在笔记软件（Obsidian、Notion 等）中使用 |
| `questions.enriched.json` | 结构化题目数据，包含 AI 解析的完整字段 |
| `explanations.cache.json` | 解析缓存，后续运行直接复用，避免重复调用 API |
| `*-复核清单.md` | 答案可能出错的题目清单，包含原题、导出答案、模型判断和风险等级 |

**AI 解析包含的字段：**

| 字段 | 内容 |
|------|------|
| 为什么选 | 正确选项的解析，80–150 字 |
| 为什么不选 | 逐个错误选项分析干扰点 |
| 复习抓手 | 一句话说明考试时如何快速识别答案 |
| 知识补充 | 相关知识点展开说明，1–4 条 |
| 同类题判断法 | 遇到同类题目的判断原理，1–4 条 |

## 配置参考

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `AI_API_KEY` | — | AI API 密钥（必填） |
| `AI_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `AI_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `AI_MAX_TOKENS` | `2000` | 每次请求最大 token 数 |
| `AI_TEMPERATURE` | `0.2` | 生成温度 |
| `AI_THINKING` | `disabled` | DeepSeek 思考模式 |
| `AI_VISION_ENABLED` | `false` | 是否把采集到的题目图片发送给支持识图的模型 |
| `AI_VISION_MAX_IMAGES` | `4` | 每道题最多随请求发送的图片数量 |
| `DOCX_FONT` | `Microsoft YaHei` | Word 文档字体 |
| `CHAOXING_STATE_PATH` | `.local/chaoxing_state.json` | 登录态保存路径 |
| `CHAOXING_HEADLESS` | `false` | 是否无头模式启动浏览器 |
| `CHAOXING_OUTPUT_DIR` | `output` | 采集输出根目录 |
| `CHAOXING_REVIEW_AFTER_COLLECT` | `true` | 采集后是否提示生成复习资料 |

> 也兼容 DeepSeek 别名：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`。

图片题说明：采集器会保存题干和选项中的图片 URL，但默认不会发送给 AI。
只有确认 `AI_MODEL` 支持 OpenAI Chat Completions 多模态 `image_url`
输入时，才把 `.env` 中的 `AI_VISION_ENABLED` 改为 `true`。
新采集的图片会用当前学习通登录态下载并写入 `data_url`，发给 AI 时优先
使用内嵌图片数据，避免第三方模型服务商直接访问学习通图片 URL 时遇到 403。
如果使用旧的 raw JSON，需要重新采集一次图片题。
生成结果中，Markdown 会用图片语法渲染题目图片，Word 文档会在题目后方
直接插入图片。

## 供 AI 编程助手使用

`skills/homework-review/` 目录包含面向 LLM 的工作流说明，供 OpenCode、Claude Code、Cursor、Cline 等工具自动调用。Skill 明确了安全边界：不自动登录、不绕过访问限制、不提交 API 密钥。

**关键词**：学习通 超星 作业导出 作业解析 复习资料 AI 复习 考试复习 DeepSeek DOCX Markdown

## 开发

```powershell
# 运行测试
uv run python -m unittest discover -s tests

# 安装 Playwright 浏览器（仅无 Edge/Chrome 时需要）
uv run playwright install chromium
```

## 许可证

[MIT](./LICENSE)
