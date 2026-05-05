# Xiaohongshu Scraper

## Run Workflow Note

`python main.py run ...` is the high-level workflow entry. `--dry-run` prints the planned `search` and optional `best-export` commands without opening a browser or visiting Xiaohongshu.

Offline best export from `run`:

```bash
python main.py run "苏州 五一 旅游" --auto-best-export --notes 5 --merged-comments --output data/exports/suzhou_mayday_best
```

`--auto-best-export` only runs the local `best-export` merge step when `--dry-run` is not used. It reads local checkpoints/history and does not visit Xiaohongshu.

一个基于 `Playwright + pandas + argparse` 的小红书浏览器抓取项目，目标是优先跑通下面这条主链路：

- 首次人工登录
- 自动保存并复用 `session/storage_state.json`
- 打开搜索页并监听真实网络响应
- 提取搜索结果基础笔记列表
- 进入详情页补全文本、图片与互动数据
- 导出 `CSV / Excel`
- 可选抓取公开可见评论，且不影响主链路稳定性
- 自动生成数据质量报告
- 可选落库到 `data/history.sqlite3`
- 支持批量关键词顺序低频运行

## 项目结构

```text
xiaohongshu_scraper/
├── main.py
├── requirements.txt
├── README.md
├── scraper/
│   ├── __init__.py
│   ├── auth.py
│   ├── comments.py
│   ├── config.py
│   ├── detail.py
│   ├── exporter.py
│   ├── logger.py
│   ├── models.py
│   ├── parser.py
│   ├── search.py
│   ├── storage.py
│   └── utils.py
├── session/
└── data/
    ├── checkpoints/
    ├── exports/
    ├── logs/
    └── raw/
```

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 Playwright 浏览器

```bash
playwright install chromium
```

## 首次登录

首次运行请先执行：

```bash
python main.py login
```

程序会打开一个可见浏览器。你需要在浏览器中手动完成登录，回到终端按回车后，程序会尝试做一次轻量 session 校验，并把登录态保存到：

```text
session/storage_state.json
```

## 普通用户入口：run

普通用户优先从 `run` 命令开始。它用于把关键词、笔记数、一级评论数、二级评论数、安全限速档位等参数收敛成一条底层 `search` 命令。

当前版本的 `run` 仍是安全预览入口：默认只输出 `search_argv`、`search_command`、`search_kwargs`，不会打开浏览器，也不会访问小红书。确认参数无误后，可以复制输出中的 `search_command` 手动执行。后续版本会在保持低风险和人工验证规则的前提下，把 `run` 接成真正的一键工作流。

常用预览命令：

```bash
python main.py run "苏州 五一 旅游" --dry-run --notes 5 --first-comments 10 --second-comments 30
```

常用选项：

- `--notes`：计划采集的笔记数。
- `--first-comments`：每条笔记计划采集的一级评论数。
- `--second-comments`：每条笔记计划采集的二级评论数。
- `--rate-profile safe|standard|fast`：安全限速档位，只调整等待时间，不增加并发，不绕过平台验证。
- `--no-comments`：只采集笔记详情，不采集评论。
- `--merged-comments`：在评论采集开启时，额外生成合并评论分析表。
- `--output` / `-o`：传递给底层 `search` 的输出文件 base path。

示例：预览一个带合并评论表的任务。

```bash
python main.py run "杭州 五一 旅游" --dry-run --notes 5 --first-comments 20 --second-comments 200 --merged-comments --output data/exports/hangzhou_mayday
```

示例：只预览笔记详情，不采集评论。

```bash
python main.py run "苏州 五一 旅游" --dry-run --notes 5 --no-comments
```

## 搜索抓取

### 基础用法

```bash
python main.py search "哈尔滨 旅游" --pages 3 --format csv
python main.py search "哈尔滨 美食" --pages 5 --format excel
python main.py search "中央大街" --pages 5 --detail
```

### 常用参数

- `query`：搜索关键词
- `--pages`：滚动采集轮次，不是站点原生传统页码
- `--format`：`csv` 或 `excel`
- `--output`：输出文件基础路径
- `--detail / --no-detail`：是否访问详情页补全正文与互动数据
- `--headed / --headless`：是否显示浏览器
- `--debug`：启用调试日志
- `--save-raw-json`：把原始响应保存到 `data/raw/`
- `--max-items-per-page`：每轮滚动最多保留多少条新笔记
- `--history / --no-history`：是否把最终结果写入 `data/history.sqlite3`
- `--detail-timeout`：详情页滚动后等待详情网络响应的秒数
- `--detail-render-wait`：详情页打开后等待可见 DOM 渲染的秒数，设置为 `0` 可关闭
- `--detail-empty-retries`：详情页完全没有网络、HTML、DOM 证据时的重试次数
- `--detail-empty-retry-wait`：空快照重试前等待的秒数

### 请求间隔控制

- `--search-delay-min` / `--search-delay-max`
- `--detail-delay-min` / `--detail-delay-max`
- `--comment-delay-min` / `--comment-delay-max`

## 详情页补全机制

搜索结果页通常只能拿到基础卡片数据，程序会在 `--detail` 开启时逐条打开详情页，并继续监听详情页真实网络响应。

`scraper/parser.py` 中已经把搜索页和详情页解析拆开了：

- `parse_search_response(...)`
- `parse_detail_response(...)`

如果你在真实环境里发现字段结构变化，优先微调这两个解析函数，而不是把硬编码散落到别的文件中。

详情页稳定性策略：

- 优先使用详情页网络响应，其次使用嵌入 HTML 状态，最后才使用渲染后的 DOM 文本兜底。
- 打开详情页后会等待标题、正文或评论容器出现，再进入解析流程，减少页面未渲染完成时的空字段。
- 如果一次详情页完全没有捕获到网络、HTML、DOM 证据，会按 `--detail-empty-retries` 做有限重试。
- 如果只拿到标题、日期、计数等不可复用字段，会记录为不完整详情，不会假装成功。
- 如果页面跳到其他 `note_id`，会记录为目标不匹配失败，避免把非目标内容写入目标笔记。

## 评论抓取

评论抓取是可选增强，默认关闭：

```bash
python main.py search "哈尔滨 旅游" --pages 3 --with-comments
```

附加参数：

- `--max-comments-per-note 50`
- `--include-replies`
- `--expand-replies` / `--max-reply-expansions-per-note 3`
- `--max-replies-per-comment 3`
- `--max-first-level-comments-per-note 20`
- `--max-second-level-comments-per-note 200`
- `--root-comment-ids "comment_id1,comment_id2"`
- `--root-comment-ids-file data/exports/run_comments.csv`

`--max-first-level-comments-per-note` and `--max-second-level-comments-per-note` enable precise per-level quotas. When neither is set, the old `--max-comments-per-note` total-only behavior is preserved. When either per-level quota is set, first-level and second-level quotas are counted independently so replies do not consume first-level quota and first-level comments do not consume reply quota. `--max-replies-per-comment 0` keeps first-level comments only; a positive value keeps at most that many second-level replies per first-level comment. `--root-comment-ids` / `--root-comment-ids-file` limits output to selected first-level comment threads for controlled incremental retries. Comment runs also export `*_comment_pagination_report.json/csv` with cap, sampling, target-filter, and reply-cap counters.

```bash
python main.py comments-only "25鑰冪爺 缁忛獙" --max-notes-total 1 --include-replies --max-comments-per-note 200
```

Example: keep 20 first-level comments and 200 second-level replies per note, with at most 10 replies under each first-level comment:

```bash
python main.py search "杭州 五一 旅游" --max-notes-total 5 --detail --with-comments --include-replies --expand-replies --max-first-level-comments-per-note 20 --max-second-level-comments-per-note 200 --max-replies-per-comment 10
```

If a verification page appears, the run records a `verification_required` runtime event, keeps the browser open, and waits for manual completion up to `--verification-wait` seconds. Use `--no-manual-verification` to keep the older immediate-failure behavior.

说明：

- 默认只抓公开可见评论
- 评论失败不会导致整次笔记采集失败
- 笔记表、评论表、失败记录表分开导出

## 导出说明

### CSV 模式

会输出多个文件：

- `*_notes.csv`
- `*_comments.csv`（开启评论时）
- `*_failed_records.csv`
- `*_quality_report.json`
- `*_quality_report.csv`

### Excel 模式

会输出一个 `xlsx` 工作簿，包含三个 sheet：

- `notes`
- `comments`
- `failed_records`

## 历史库与质量报告

默认情况下，每次搜索完成后会尝试把本次结果写入：

```text
data/history.sqlite3
```

历史库包含运行记录、笔记、评论、失败记录，以及每次运行和笔记之间的关联表。
如果本地环境不允许 SQLite 写入，程序不会丢弃已导出的 CSV/Excel，而是额外写出：

```text
*_history_error.txt
```

每次运行还会生成质量报告：

```text
*_quality_report.json
*_quality_report.csv
```

质量报告会统计字段覆盖率，例如 `title`、`content`、`publish_time`、`ip_location`、`tags`、互动数字段，以及失败阶段分布。

## 批量关键词

可以把关键词写入 UTF-8 文本文件，每行一个关键词，空行和 `#` 开头的注释会被忽略：

```text
哈尔滨 旅游
哈尔滨 美食
# 中央大街
```

顺序低频运行：

```bash
python main.py batch keywords.txt --resume --pages 1 --max-notes-total 5 --headed --detail --no-comments --save-raw-json --keyword-delay-min 30 --keyword-delay-max 60
```

批量命令默认不会因为单个关键词失败而中断整个批次，会在 `data/batches/` 写出批次报告。
正式扩量时不要加 `--force-detail`，否则会刻意重跑已处理详情页。

## 渐进式落盘

程序在运行过程中会持续保存中间结果：

- 每完成一轮搜索滚动，保存一次 `notes_progress.csv`
- 每完成评论批次，也会更新中间结果
- 同时写出一个 `checkpoint.json`

目录：

- `data/exports/`
- `data/checkpoints/`

## session 机制说明

搜索命令执行前，程序会先检查：

1. `session/storage_state.json` 是否存在
2. 轻量 session 校验是否通过

如果不通过，会自动退回到人工登录流程，然后再继续跑主链路。

## 常见报错排查

### 1. 没监听到搜索响应

可能原因：

- 页面尚未真正加载到搜索结果
- 页面结构或请求路径变了
- 网络过慢，等待时间不够

可以尝试：

- 使用 `--headed` 观察页面
- 增加 `--pages`
- 开启 `--debug`
- 开启 `--save-raw-json` 检查抓到的真实响应

### 2. 详情页补全失败

项目默认优先走详情页网络 JSON，不直接依赖 DOM 文本兜底。如果站点详情接口结构有变，请调整：

- `scraper.parser.looks_like_detail_response`
- `scraper.parser.parse_detail_response`

### 3. session 明明存在但仍提示重登

`storage_state.json` 存在不代表登录态一定有效。站点 cookie 过期或页面选择器变化时，轻量校验可能失败。最简单的处理方式是重新执行：

```bash
python main.py login
```

## 说明

- 所有抓取都基于浏览器真实访问页面和监听真实网络响应
- 不伪造签名、不绕过验证码、不提供规避平台安全机制的逻辑
- 解析部分采用了防御式处理，但真实字段仍可能需要按当前响应微调

## 待补详情队列

当质量报告出现 `detail_incomplete_note_ids` 时，先离线生成待补详情队列，不要直接扩大 live 抓取：

```bash
python main.py detail-queue "哈尔滨 旅游" --max-notes-total 5
```

该命令只读取本地 checkpoint，并在 `data/queues/` 写出：

- `*_detail_queue.csv`
- `*_detail_queue.json`
- `*_detail_queue_note_ids.txt`

如果确认要只重跑这些不完整详情，再使用 `--note-ids-file` 白名单过滤：

```bash
python main.py search "哈尔滨 旅游" --resume --detail --no-comments --note-ids-file data/queues/<queue>_note_ids.txt --save-raw-json --debug --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10
```

这条命令会访问小红书；执行前应确认账号风险和访问频率。

## 最佳合并表导出

当同一批笔记经历过搜索、详情、评论、离线重解析等多轮运行后，可以用 `best-export` 离线合并本地最佳版本：

```bash
python main.py best-export "哈尔滨 旅游" --max-notes 10 --output data/exports/哈尔滨_旅游_best_merged
```

该命令不会访问小红书，只读取本地 `data/history.sqlite3` 和 `data/checkpoints/`。默认会用最新满足数量要求的 checkpoint 作为行集合，再从历史记录里补全这些 note_id 的详情字段和评论。

输出包括：

- `*_notes.csv`
- `*_comments.csv`
- `*_failed_records.csv`
- `*_quality_report.json`
- `*_quality_report.csv`
- `*_merge_report.json`

合并规则是字段级的：互动数优先保留更大的有效数字，`search_rank/source_page` 优先保留更小排名，正文会过滤页面噪声、评论误入正文、重复 DOM 文本和历史误入 tag 的正文片段。它不会伪造缺失详情；如果质量报告仍显示 `detail_incomplete_note_ids`，需要再走 `detail-queue` 或人工判断是否重跑。

## 安全 workflow 计划

当准备批量扩量时，先生成离线 workflow 计划，不要直接运行 live `batch`：

```bash
python main.py workflow-plan data/batches/workflow_keywords_harbin.txt --max-notes-total 5 --output data/batches/workflow_harbin_plan
```

该命令不会访问小红书，只会读取本地 checkpoint/history，并写出：

- `data/batches/*_plan.csv`
- `data/batches/*_plan.json`
- `data/batches/*_plan_commands.txt`
- `data/queues/*_review_detail_queue.*`
- `data/queues/*_recommended_detail_queue.*`

`review` 队列用于人工审查全部待补/blocked 项；`recommended` 队列只保留建议重跑的 note_id。后续 live 重跑应优先使用 `recommended_detail_queue_note_ids.txt`，不要把 `blocked_non_reusable_detail` 自动放进重跑。

计划文件中的 `search_command` 和 `detail_rerun_command` 会访问小红书，执行前需要明确确认账号风险和访问频率。`review_queue_command`、`recommended_queue_command`、`quality_command` 是离线命令。

## 速度优化待办

当前详情路径的主要速度瓶颈是页面渲染等待：为了避免正文、IP、标签、评论区域尚未渲染就被判定为空，程序会保守等待 DOM 和详情网络响应。这会提高稳定性，但会拉长单条详情耗时。

后续速度优化应优先做：

- 将 `--detail-render-wait` 和 `--detail-timeout` 做成基于命中证据的自适应等待，已经拿到可复用详情时立即结束。
- 统计每条笔记的 `after_open`、`after_scroll`、`final` raw probe 命中率，找出可安全缩短等待的阶段。
- 在不增加账号风险的前提下，评估网络响应优先路径、详情队列小批量重跑、离线合并，减少重复打开详情页。
- 不建议为了速度加入绕过验证码、风控、访问控制或高频请求逻辑。

## 离线重算详情 DOM

如果详情 DOM 解析规则修复后，需要用已有 raw 重新生成 CSV，不要重新访问小红书，使用：

```bash
python main.py reparse-detail-dom --checkpoint data/checkpoints/<run>_checkpoint.json --detail-dom data/raw/<run>/detail_dom.jsonl --output data/exports/<run>_reparsed
```

该命令只读取本地 `checkpoint` 和 `detail_dom.jsonl`，会重新写出 notes、failed_records 和 quality_report。它适合修复正文重复、评论 UI 混入正文、location 误识别等 parser 问题。

默认还会在 `data/checkpoints/` 写出 `<output_name>_checkpoint.json`，让后续 `--resume` 优先使用清洗后的 checkpoint。需要指定位置时可加：

```bash
--checkpoint-output data/checkpoints/<clean_run>_checkpoint.json
```

## Comment Sentiment Fields

`*_comments.csv` is structured for downstream sentiment analysis. It keeps `comment_content` as the raw public comment text and adds `comment_content_clean` for NLP-friendly text with Xiaohongshu emoji markers such as `[微笑R]` removed.

Relationship fields:

- `comment_level`: `1` for first-level comments, `2+` for replies.
- `parent_comment_id`: root parent comment id when available.
- `reply_to_comment_id`: direct target comment id when available.
- `reply_to_user` / `reply_to_user_id`: direct target user when available.
- `is_author_comment`: `1` when the platform marks the comment as author-owned or the commenter id matches the note author id.

The raw platform payload reference is still preserved in `raw_comment_json`. Use `comment_content_clean` only as an analysis convenience, not as the evidence field.

For larger public-comment samples, raise `--max-comments-per-note`. The collector will keep scrolling the rendered comment container for a bounded number of rounds and stop when the requested cap is reached or no new public comment payloads appear.

Use `--include-replies` to keep second-level replies that appear in public comment payloads. Use `--expand-replies` only when you want the browser to click a bounded number of visible reply expansion controls; limit it with `--max-reply-expansions-per-note`.

Comment exports also include note-level completeness markers such as `note_comment_cap`, `note_expected_comment_count`, `note_collected_comments`, `note_comments_reached_cap`, `note_comments_sampled`, and `note_comments_has_more`. Treat rows with `note_comments_sampled=1` as a bounded sample rather than a complete comment section.
