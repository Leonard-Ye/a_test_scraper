这个项目和上一个 `xianyu-price-tracker` 的实现思路不一样。

上一个闲鱼项目的核心是：**打开真实浏览器 → 访问搜索页 → 拦截网页自己发出的接口响应 → 解析 JSON**。

这个 `LittleCrawler` 的小红书模块更进一步：**用 Playwright 维持真实浏览器环境和登录态，但真正取数据时主要是用 `httpx` 主动请求小红书 Web API；请求前通过 Playwright 在真实页面环境里生成小红书需要的签名请求头。**

也就是说，它不是单纯“监听页面响应”，而是：

```text
启动程序
→ 选择平台爬虫
→ 打开浏览器 / CDP 连接真实浏览器
→ 登录或复用浏览器状态
→ 从浏览器上下文提取 cookies
→ 创建 XiaoHongShuClient
→ 用浏览器页面环境生成 X-S / X-T / x-s-common 等签名头
→ 用 httpx 主动请求小红书接口
→ 搜索笔记
→ 获取详情
→ 获取评论
→ 存储到 JSON / CSV / SQLite / MongoDB / Excel 等
```

项目 README 写的是一个“多平台社交媒体爬虫框架”，支持小红书、知乎、小黄鱼/闲鱼，并说明配置里可以选 `PLATFORM`、`CRAWLER_TYPE`、`LOGIN_TYPE`、`SAVE_DATA_OPTION`、`ENABLE_CDP_MODE` 等参数。README 还说数据存储支持 CSV、JSON、SQLite、MySQL、MongoDB、Excel。([GitHub][1])

但是我看当前 `main` 分支源码时发现一个不一致点：`src/platforms` 目录当前只显示 `xhs` 和 `zhihu`，没有 `xhy` 目录；`main.py` 里的 `CrawlerFactory.CRAWLERS` 也只注册了 `"xhs": XiaoHongShuCrawler` 和 `"zhihu": ZhihuCrawler`，没有注册 `xhy`。所以 README 说支持小黄鱼/闲鱼，但当前主分支可见代码里，真正完整可读的重点是小红书和知乎，小黄鱼/闲鱼这块至少在当前源码结构中没有像上一个仓库那样直接可见。([GitHub][2])

它的小红书实现核心在 `src/platforms/xhs/core.py` 和 `src/platforms/xhs/client.py`。`core.py` 负责浏览器启动、登录、搜索流程、详情补全、评论抓取、媒体抓取；`client.py` 负责具体 API 请求、签名请求头、搜索接口、详情接口、评论接口。([GitHub][3])

第一层关键技术是 **Playwright + CDP 模式**。项目配置里把 `ENABLE_CDP_MODE=True` 作为推荐项，README 注释写的是“CDP模式（推荐，反检测更强）”。源码里如果开启 CDP 模式，就调用 `launch_browser_with_cdp()`；如果失败，会回退到标准 Playwright 浏览器模式。标准模式下还会注入 `libs/stealth.min.js`，注释写明这是用于降低被网站检测为爬虫的脚本。([GitHub][1])

第二层关键技术是 **持久化浏览器上下文**。它不是简单保存一个 `storage_state.json`，而是用 Playwright 的 `launch_persistent_context()`，把用户数据目录放到 `browser_data/{platform}_user_data_dir` 这类路径下。源码注释直接写了“save login state to avoid login every time”，也就是通过持久化浏览器 profile 来复用登录状态。([GitHub][3])

第三层关键技术是 **多种登录方式**。配置里 `LOGIN_TYPE` 可以是 `qrcode`、`phone`、`cookie`。登录类 `XiaoHongShuLogin` 里会根据配置选择二维码登录、手机号登录或 cookie 登录；登录成功判断主要看 `web_session` 这个 cookie 是否从“未登录时的值”变成了新值。二维码登录会找页面里的二维码图，展示给用户扫码，并轮询登录状态。([GitHub][1])

第四层，也是这个项目和简单浏览器爬虫最大的区别：**它会生成小红书 Web API 需要的签名请求头**。`XiaoHongShuClient._pre_headers()` 会根据请求参数调用 `sign_with_playwright()`，然后把生成出来的 `X-S`、`X-T`、`x-S-Common`、`X-B3-Traceid` 塞进 headers。这个签名过程不是纯 Python 离线完成，而是借助 Playwright 页面环境调用浏览器里的 JS 函数。([GitHub][4])

具体看 `playwright_sign.py`，它会先拼接待签名字符串，算 MD5，然后通过 `page.evaluate()` 调用页面里的 `window.mnsv2(...)` 生成签名核心值，最后构造 `x-s` 和 `x-s-common`。这说明它依赖真实小红书页面环境来辅助签名，而不是简单抓 HTML，也不是只监听浏览器 response。([GitHub][5])

第五层关键技术是 **httpx 主动请求接口**。`XiaoHongShuClient` 的 `_host` 是 `https://edith.xiaohongshu.com`，搜索笔记时调用 `/api/sns/web/v1/search/notes`，请求体里包含 `keyword`、`page`、`page_size`、`search_id`、`sort`、`note_type`。所以它的搜索数据不是从页面 DOM 抠出来的，而是通过带签名 headers 的 API 请求拿到。([GitHub][4])

第六层是 **搜索 → 详情 → 评论的链式采集**。`search()` 里会按关键词和页码调用 `get_note_by_keyword()`，从搜索结果中拿 `id`、`xsec_source`、`xsec_token`，然后并发调用 `get_note_detail_async_task()` 获取每条笔记详情。详情拿到后会 `update_xhs_note()` 保存，并把 `note_id` 和 `xsec_token` 收集起来，随后调用 `batch_get_note_comments()` 抓评论。([GitHub][3])

第七层是 **详情接口 + HTML 兜底解析**。详情优先通过 `get_note_by_id()` 请求 `/api/sns/web/v1/feed`。如果接口拿不到，`get_note_detail_async_task()` 会退回到 `get_note_by_id_from_html()`；这个兜底方法访问笔记详情页 HTML，然后从页面里的 `window.__INITIAL_STATE__` 里解析 `noteDetailMap`。这比只依赖一个接口更稳，因为接口失败时还能尝试从页面初始状态里恢复详情数据。([GitHub][3])

第八层是 **评论接口分页抓取**。`client.py` 里一级评论接口是 `/api/sns/web/v2/comment/page`，参数包括 `note_id`、`cursor`、`xsec_token` 等；二级评论接口是 `/api/sns/web/v2/comment/sub/page`。`get_note_all_comments()` 会根据 `has_more` 和 `cursor` 翻页，同时受 `max_count` 限制；如果开启二级评论，才继续抓子评论。([GitHub][6])

第九层是 **并发控制、重试、间隔和失败兜底**。核心流程里用 `asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)` 控制并发；详情和评论抓取后会 `sleep(config.CRAWLER_MAX_SLEEP_SEC)`；`client.request()`、`get_note_by_id_from_html()` 等关键请求用了 `tenacity` 重试；遇到 `DataFetchError` 或 `KeyError` 时单条详情返回 `None`，不会直接让整个任务崩掉。([GitHub][3])

第十层是 **可插拔存储层**。小红书存储通过 `XhsStoreFactory` 按 `SAVE_DATA_OPTION` 选择 CSV、DB、JSON、SQLite、MongoDB、Excel 等实现；`update_xhs_note()` 会从笔记详情里整理 `note_id`、`type`、`title`、`desc`、`time`、`user_id`、`nickname`、图片、视频、互动信息等字段。([GitHub][7])

所以，如果一句话概括这个项目的小红书实现：

**LittleCrawler 是“真实浏览器环境 + API 客户端”的混合方案：浏览器负责登录态、Cookie、JS 签名环境和反自动化兼容；httpx 客户端负责主动请求搜索、详情、评论等接口；Playwright 在中间承担签名生成、登录维持和兜底页面解析的作用。**

和上一个闲鱼项目对比，差别很关键：

| 对比点    | xianyu-price-tracker     | LittleCrawler 小红书模块                |
| ------ | ------------------------ | ---------------------------------- |
| 数据来源   | 拦截网页自身搜索接口响应             | 主动请求小红书 Web API                    |
| 浏览器作用  | 登录 + 打开搜索页 + 监听 response | 登录 + 持久化状态 + CDP/stealth + JS 签名环境 |
| 是否处理签名 | 基本不手写签名，借网页自己请求          | 明确生成 `X-S`、`X-T`、`x-s-common`      |
| 详情补全   | 主要搜索结果页数据                | 搜索后继续请求详情接口，失败再解析 HTML             |
| 评论     | 上个项目没有明显主链路评论            | 有一级评论、可选二级评论                       |
| 工程复杂度  | 较轻量                      | 明显更工程化，平台层、存储层、服务层分离               |

它“更稳”的地方在于：不是只靠 DOM，不是只靠一个页面响应；它有持久化浏览器状态、CDP 模式、签名头生成、API 主动请求、详情 HTML 兜底、评论分页、并发限制、重试、存储抽象。它“不稳”的地方也很明显：小红书签名函数、headers 结构、`xsec_token`、`window.__INITIAL_STATE__`、评论接口字段，只要平台改动，就可能需要维护。README 里的小黄鱼/闲鱼支持也和当前源码可见结构不完全一致，至少当前主分支里我没有看到 `src/platforms/xhy` 的实现。([GitHub][1])

[1]: https://github.com/pbeenigg/LittleCrawler "GitHub - pbeenigg/LittleCrawler: LittleCrawler（小爬虫），支持小红书（xhs）｜ 知乎（zh）|  闲鱼（xy）平台的公开信息抓取。 · GitHub"
[2]: https://github.com/pbeenigg/LittleCrawler/tree/main/src/platforms "LittleCrawler/src/platforms at main · pbeenigg/LittleCrawler · GitHub"
[3]: https://github.com/pbeenigg/LittleCrawler/blob/main/src/platforms/xhs/core.py "LittleCrawler/src/platforms/xhs/core.py at main · pbeenigg/LittleCrawler · GitHub"
[4]: https://github.com/pbeenigg/LittleCrawler/blob/main/src/platforms/xhs/client.py "LittleCrawler/src/platforms/xhs/client.py at main · pbeenigg/LittleCrawler · GitHub"
[5]: https://github.com/pbeenigg/LittleCrawler/blob/main/src/platforms/xhs/playwright_sign.py "LittleCrawler/src/platforms/xhs/playwright_sign.py at main · pbeenigg/LittleCrawler · GitHub"
[6]: https://raw.githubusercontent.com/pbeenigg/LittleCrawler/main/src/platforms/xhs/client.py "raw.githubusercontent.com"
[7]: https://github.com/pbeenigg/LittleCrawler/blob/main/src/storage/xhs/__init__.py "LittleCrawler/src/storage/xhs/__init__.py at main · pbeenigg/LittleCrawler · GitHub"
