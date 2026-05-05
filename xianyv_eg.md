我按源码看了一遍。这个仓库“稳定自动得到闲鱼数据”的核心不是破解接口，也不是直接伪造请求，而是：

**用 Playwright 启动真实 Chromium 浏览器，先人工登录一次并保存登录态；后续复用 `storage_state.json` 打开闲鱼搜索页，然后拦截网页自己发出的搜索接口 JSON 响应，再从 JSON 结构里解析商品数据。**

它的技术路线可以概括成：

```text
人工登录一次
→ 保存浏览器登录态 storage_state.json
→ 后续无头浏览器复用登录态
→ 打开闲鱼搜索页
→ 监听页面 response
→ 捕获 JSON 响应
→ 过滤出 pc.search 搜索接口
→ 从 data.resultList[].data.item.main 提取商品字段
→ 去重
→ 统计价格
→ 导出 CSV / Excel
```

第一层稳定性来自“真实浏览器 + 会话复用”。`auth.py` 里 `login_and_save()` 会用 Playwright 启动可见 Chromium，进入 `https://www.goofish.com/`，让用户手动登录；它通过轮询 cookies 判断是否登录成功，关键判断是 cookies 中出现 `unb` 和 `_m_h5_tk`，然后把浏览器上下文保存到 `session/storage_state.json`。这意味着它不是完全免登录自动化，而是“首次人工登录 + 后续复用 session”。([GitHub][1])

第二层稳定性是“启动搜索前先校验 session”。`load_context()` 会用保存好的 `storage_state.json` 创建新的浏览器上下文，并设置常见 Chrome User-Agent；`check_session_valid()` 会打开闲鱼首页并检查 cookies 里是否仍有 `_m_h5_tk` 和 `unb`。CLI 入口在搜索前也会先判断 session 文件是否存在，再加载上下文并检查有效性；如果失效，就提示重新登录，而不是继续抓取导致一堆空结果。([GitHub][1]) ([GitHub][2])

第三层稳定性是“不解析 DOM，而是抓网页真实接口返回”。`search.py` 里定义搜索地址为 `https://www.goofish.com/search?q={query}&page={page}`，然后用 `page.on("response", handle_response)` 监听页面响应；它只处理 `content-type` 含 JSON 的响应，并把响应体 `response.json()` 存进列表。也就是说，它不是靠 CSS 选择器去页面里抠文字，而是让闲鱼网页自己发请求，再把返回的 JSON 拦下来。([GitHub][3]) ([GitHub][3])

真正的数据接口是 README 里写的 `mtop.taobao.idlemtopsearch.pc.search`，数据路径是 `data.resultList[].data.item.main`。`parser.py` 也验证了这一点：它只解析 `api` 字段里包含 `pc.search`、且不包含 `shade` 的响应，然后进入 `raw["data"]["resultList"]`，再从每条 `entry["data"]["item"]["main"]` 中提取字段。([GitHub][4]) ([GitHub][5])

第四层稳定性是“防御式字段提取”。它没有假设每个字段一定在一个固定位置，而是在多个可能路径里兜底取值。例如 `item_id` 会从 `exContent.itemId`、`clickParam.args.id`、`detailParams.itemId` 里依次取；标题也会从 `exContent.title` 或 `detailParams.title` 取。价格会去掉 `￥` 和逗号再转 `float`，失败就置为 `None`；`publishTime` 会按毫秒时间戳转成日期字符串，失败则保留原值；`wantNum` 会转成整数，失败则置为 0。([GitHub][5]) ([GitHub][5])

第五层稳定性是“去重”。`parse_items()` 先优先按 `item_id` 去重；如果没有 `item_id`，就用“标题 + 卖家昵称 + 日期”构造一个 fallback fingerprint。冲突时默认保留 `created_time` 更新的记录，也支持 `lowest_price` 逻辑。这个设计能减少多页搜索、重复曝光、接口重复返回造成的重复商品。([GitHub][5])

第六层稳定性是“限速和进度”。`search_keyword()` 支持 `delay_min` 和 `delay_max`，每页之间用 `random.uniform(delay_min, delay_max)` 随机暂停，默认 1.5 到 3 秒。CLI 也把这两个参数暴露出来，让用户可以降低访问频率。它还支持 `on_page_done` 回调，Web 端用这个做进度推送。([GitHub][3]) ([GitHub][2])

第七层是“数据落地和导出”。`exporter.py` 用 pandas 把解析后的商品列表转成 DataFrame，然后按字段顺序导出 CSV 或 Excel；CSV 使用 `utf-8-sig`，Excel 使用 `openpyxl`。导出字段包括 `item_id`、`title`、`price`、`condition`、`seller_nick`、`location`、`category`、`want_count`、`created_time`、`images`。([GitHub][6])

第八层是“CLI 和 Web 共用同一套核心”。`main.py` 作为 CLI 入口，调用的是 `auth.load_context()`、`auth.check_session_valid()`、`search_keyword()`、`parse_items()`、`exporter.export()`；`server.py` 的 FastAPI Web 入口也导入并调用同一批核心函数，没有另外写一套抓取逻辑。Web 端还用了 `_browser_lock = asyncio.Lock()` 防止并发浏览器任务互相冲突，并通过 SSE 流式推送登录、搜索和进度状态。([GitHub][2]) ([GitHub][7]) ([GitHub][7])

它采用的关键技术可以归纳成这几类：

| 技术                    | 作用                                    |
| --------------------- | ------------------------------------- |
| Playwright / Chromium | 启动真实浏览器，完成登录、访问搜索页、监听网络响应             |
| `storage_state.json`  | 保存登录态，后续复用，不必每次扫码                     |
| Cookie 状态检测           | 用 `unb` 和 `_m_h5_tk` 判断登录是否有效         |
| `page.on("response")` | 拦截网页自己发出的接口响应                         |
| JSON 响应解析             | 从 `pc.search` 接口返回体里拿商品数据             |
| 防御式字段提取               | 字段缺失或结构变化时尽量不中断                       |
| 去重逻辑                  | 按 `item_id` 或 fallback fingerprint 去重 |
| 随机延迟                  | 多页抓取时降低连续高频访问                         |
| pandas + openpyxl     | 导出 CSV / Excel                        |
| Click + Rich          | CLI 命令和终端进度/表格展示                      |
| FastAPI + SSE         | Web UI、登录状态、搜索进度、下载链接                 |
| asyncio Lock          | Web 端防止多个浏览器任务并发冲突                    |

但要注意，这个项目的“稳定”是相对稳定，不是绝对稳定。它稳定的原因是避开了手写签名、逆向参数、DOM 选择器易变这些脆弱点，改用真实浏览器和真实接口响应；但它仍然依赖闲鱼网页结构、`pc.search` 接口结构、cookie 有效期和平台风控策略。如果闲鱼改了接口名、返回路径、登录状态 cookie，或者无头浏览器触发限制，它还是会失效。README 也明确提示要保存 session、控制抓取频率，并把会话文件视为敏感信息。([GitHub][4])

最重要的结论是：**它不是“全自动破解闲鱼数据”，而是“人工登录一次后，借助真实浏览器自动访问搜索页，并拦截闲鱼网页自身返回的搜索接口 JSON”。** 这就是它相比普通爬虫更稳的根本原因。

[1]: https://github.com/Ray-Yuan21/xianyu-price-tracker/blob/main/scraper/auth.py "xianyu-price-tracker/scraper/auth.py at main · Ray-Yuan21/xianyu-price-tracker · GitHub"
[2]: https://github.com/Ray-Yuan21/xianyu-price-tracker/blob/main/main.py "xianyu-price-tracker/main.py at main · Ray-Yuan21/xianyu-price-tracker · GitHub"
[3]: https://github.com/Ray-Yuan21/xianyu-price-tracker/blob/main/scraper/search.py "xianyu-price-tracker/scraper/search.py at main · Ray-Yuan21/xianyu-price-tracker · GitHub"
[4]: https://github.com/Ray-Yuan21/xianyu-price-tracker "GitHub - Ray-Yuan21/xianyu-price-tracker · GitHub"
[5]: https://github.com/Ray-Yuan21/xianyu-price-tracker/blob/main/scraper/parser.py "xianyu-price-tracker/scraper/parser.py at main · Ray-Yuan21/xianyu-price-tracker · GitHub"
[6]: https://github.com/Ray-Yuan21/xianyu-price-tracker/blob/main/scraper/exporter.py "xianyu-price-tracker/scraper/exporter.py at main · Ray-Yuan21/xianyu-price-tracker · GitHub"
[7]: https://github.com/Ray-Yuan21/xianyu-price-tracker/blob/main/server.py "xianyu-price-tracker/server.py at main · Ray-Yuan21/xianyu-price-tracker · GitHub"
