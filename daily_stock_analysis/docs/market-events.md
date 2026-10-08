# 今日市场事件 / Market events

## 跨行业机会覆盖（v3） / Cross-sector coverage

九类固定阅读方向：AI 应用/企业软件、网络安全、半导体/AI 基建、电力电网、工业自动化、医疗、消费、金融、能源黄金。`sector_radar` 只归类本期选中的最多八个事件，保留事件键与原始证据；不是全市场价格扫描、公司估值排名或自动买入推荐，关键词可能漏报或误报。新闻线索不等于上涨催化，也不将候选加入持仓。模型需区分短线、主题和长期，明确反向情景、验证与失效条件。

状态为 `evidence_watch`（有带时间来源报道，仍待核验）、`verification_required`（来源/时点待核实、预告或已撤回/争议）、`no_selected_evidence`（选中材料未覆盖，不代表无机会）。读取历史会按后续人工核验重算观察状态，原归档不改写；界面内新增撤回记录也会即时降级。报告文本展示全部最多八个事件，再列行业覆盖；缓存旧文本仍是当时版本。

美股大盘原新闻采集增加同样三组行业主题，原搜索服务缓存和时效策略继续适用；市场事件附录仍只复用采集结果，不再另开模型或通知。新增检索可能增加搜索额度使用，不保证每个行业取得有效证据。网页可取消跨行业搜索以恢复两组基础检索。关闭搜索时仍可对已有材料归类，不声称已联网扫描。

English: Nine sector buckets classify selected evidence, not all-market trading opportunities. Three optional bounded search batches extend discovery beyond holdings. A timestamped report is a lead, not a verified claim or entry signal. Unknown timing, disputed or retracted claims are downgraded. Missing coverage is not absence of opportunity. Daily US reviews collect these themes too; existing report capture adds no extra model call. New response fields are optional for old clients.

回滚本次前后端补丁即可移除行业展示与额外检索；无新数据库列，保留历史快照，旧客户端忽略追加字段。既有中文专题无独立英文副本，本节提供英文契约，网页中英标签同步。

## 使用入口

Web 侧边栏 **市场事件**（`/market-events`）。选择 A 股、港股、美股或全球，点击“生成今日简报”。页面打开和查看历史只读本地数据，不发起新闻搜索、模型调用、源启用或通知。

可独立选择：

- 使用已配置的新闻搜索渠道：复用 `SearchService`，基础两组当期查询；默认勾选跨行业扫描时另加三组（总计五组），每组最多 8 条、12 秒硬截止。可关闭跨行业检索；没有渠道或单组搜索失败分别披露，单组异常不取消后续组。
- 刷新已启用资讯源：复用 RSS/Atom/NewsNow 采集和 SSRF 防护，不自动创建或重新启用源。单次最多刷新 6 个匹配市场的源，超限显式披露。全局自动采集开关仍遵守原有行为。
- AI 条件式解读：复用已有 `GeminiAnalyzer.generate_text` 及现有模型配置，可能产生模型费用；不新增模型、密钥或自动化配置。未配置模型、失败、JSON 不合约或引用越界时保留原始证据并显示降级原因，不伪造 AI 结论。
- 手工补充最多 5 条快讯（页面提供单条输入）：填标题、摘要、可选链接、发布时间及明确的事件排期。截图须先转成文字；本版未实现图片 OCR。没有原文链接时默认待核实，不能由输入内容自行声明“已确认”。

资讯源设置可从现有模板创建并启用源，或切换已有源的启用状态；这是用户显式操作。NewsNow 公共示例实例可能失效或限流，生产环境建议自建或使用可控实例，详见 [资讯源文档](intelligence-sources.md)。

## 证据与时间契约

- 标题、摘要、URL、来源名、原始发布时间构成证据版本。URL 移除常见密钥与跟踪参数，拒绝危险协议、凭证和非公网 IP 链接；新闻内容及模型输出均作为数据，不作为工具指令。
- `published_at` 是来源发布时间，`event_at` 是明确提供的事件发生时点（默认未知），`first_seen_at` 是本模块第一次留存该内容版本的 UTC 时间，`retrieved_at` 是留存时的采集时间。首次留存不能冒充首次发布，也不代表互联网最早出现时间。
- 带时区的发布时间统一为 UTC；仅有日期单独标记，无时区旧记录标为待核实，不擅自加北京时间或 UTC。新 RSS/Atom/NewsNow 采集在 `raw_payload` 保留原始时间，旧数据不猜测、不回填。
- 今日按所选市场时区分组（A 股上海、港股香港、美股纽约、全球 UTC）；UI 的具体时间统一展示北京时间。新闻窗口为最近 48 小时；日期精度记录按当天及前两个自然日粗筛。发布时间在未来的记录隔离，发布时间不明的记录显式标记，不写“今日发生”。明确提供 `event_at` 且发生时间在未来 7 天内的预告单列“未来已排期，尚未发生”，不因公告较早就丢弃，也不生成尚未发布的实际数据；未提供排期、排期已过或超过 7 天仍执行原新闻窗口。此规则只作用于取得的材料，不会补抓旧公告。
- 原始条目读取限于最近 3 天采集数据，每个相关市场最多 100 条；超过上限显示截断，不能宣称全网扫描完整。
- 同标题（忽略大小写/空格）、同发布日期且排期一致的报道保守合并，保留每条来源；不同排期不会合并。不同标题的语义聚类尚未实现；多篇转载不等于多个独立信源。更新的内容创建新版本，不覆盖旧版。
- 最多选择 8 个事件，规则版本 `market-events-v3`：先匹配财经主题（增加九类行业），再按明确持仓代码、目标市场词、跨市场传导线索及来源市场标签筛选；先每主题一条，再按阅读优先级补位，各行业最多两条。英文词采用边界匹配，避免把 `turmoil` 误判为 `oil`。未命中规则的材料仍归档，排除计数独立披露；这不表示它们绝对没有市场影响，词表会漏报，需结合原文复核。
- 阅读优先级由上述相关性、明确排期/时效和已知官方域名链接共同构成，不是统计胜率或全市场重要性的客观评分。官方链接仅增加阅读优先级，不增加真实性认证。单期地缘/房地产各最多 2 条，宏观/科技/公司各最多 3 条，不为填满 8 条突破主题限额，也不将同主题的不同事实强行合并。历史版本保留原排序。

## 核验与解读

“官方链接”只表示 URL 属于已知官方域名，不表示系统读过并验证全部条款。所有自动采集新闻默认为“来源报道”或“待核实”；本版不提供自动真实性认证。

用户可对具体事件版本追加 **人工核实 / 存在争议 / 已撤回 / 待核实** 记录，必须提供依据链接和具体核验说明。记录附带服务端核验时间及 `user_attestation` 标记，不接受回填核验时间。历史简报保留当时状态；最新核验作为独立覆盖层展示。撤回/争议后的旧 AI 解读隐藏，历史数据仍保留。相同标题的新内容版本不会继承旧版本的“已核实”。

AI 输出仅包含：影响路径、潜在受益方向、风险、反向情景、影响周期、验证条件、失效条件和持仓可能关联。引用必须来自对应事件的证据 ID，持仓代码和市场必须来自本期明确标注来源的关联集合；不存在的引用、额外交易字段、重复事件输出拒绝整批解读。结构校验不能证明推理内容正确，界面始终标记为 AI 假设。

每个事件最多向模型提供 3 条证据（官方域名链接优先，但不自动核实），控制转载堆积导致的上下文膨胀；其余来源仍完整归档并在页面展示，模型不得引用未提供的证据。

不核验实时行情、NAV、ETF 成分权重，不生成可执行价位、数量、资金安排或收益保证。不因新闻生成决策信号、模拟成交或券商订单。页面可补充含时区的排期，但未单独接入经济日历，不能声称已自动完整收集今晚所有事件。页面与文本附录均展示模型解读状态；源连通不等于 AI 解读可用。

## 持仓、历史与研报集成

- 持仓关联优先通过现有账本的期初持仓、成交与公司行动重放正股数，只读事务，不调用估值、不更新持仓缓存。仅发送代码和市场给模型，不发送账户名、数量、金额和成本。已清仓、未来交易、自选、目标配置不算当前持仓；无账本账户时可显式配置下述档案参考，默认不启用。
- 账本尚未录入且未显式配置档案时显示“未读取到已记录持仓”，不推断真实空仓。系统不自动扫描聊天历史、档案或券商账户；档案关联须用户主动配置，正式数量/现金核算仍需通过现有持仓功能录入并核对。
- 每次简报不可变归档，保留当时证据、选取规则、持仓集合和解读。请求键幂等：超时后使用同键重试；同键不同参数拒绝。不能指定历史 `as_of` 重新生成事前证据。
- A 股、港股、美股大盘复盘复用**本次已采集新闻**，附加确定性的来源/核验状态区块，并在结构化载荷增加 `market_events`。不额外搜索、不额外调用模型、不修改云端或本地调度，不另发一条通知。原有大盘 AI 正文仍走原分析流程；新闻快照卡片本身未再次调用 AI 时会明确显示“未请求 AI 解读”。
- 没有来源、来源失败、只有缓存、条目截断、模型失败分别披露；“没有足够证据”不等于“今天没有重大消息”。

## API 与存储

沿用已有全局 API 认证策略：

- `GET /api/v1/market-events?market=cn&limit=30`：摘要历史。
- `POST /api/v1/market-events`：生成并留档，字段 `request_key / market / language / refresh_sources / search_news / scan_sectors / analyze / manual_items`；追加 `scan_sectors` 默认 true，仅在搜索开启时增加检索。
- `POST /api/v1/market-events/jobs`：相同输入，返回 202 和后台任务状态，网页使用此入口。
- `GET /api/v1/market-events/jobs/{request_key}`：只读查询阶段及归档 ID，不触发生成；完成后优先从持久归档恢复。
- `POST /api/v1/market-events/{id}/retry-analysis`：仅传新的 `request_key`，只补该快照缺失且未被争议/撤回阻止的解读，可能产生模型费用。
- `GET /api/v1/market-events/{id}`：冻结简报及后续独立核验历史。
- `POST /api/v1/market-events/{id}/verifications`：追加 `event_key / status / evidence_url / note`。
- `PATCH /api/v1/intelligence/sources/{id}`：仅更新 `enabled`，不改变源地址。

新增 `market_news_evidence`、`market_event_briefs`、`market_event_verifications`，沿用 SQLAlchemy `create_all` 加表，不改变旧表列。不定期清理这些研究证据，避免原资讯 30 天清理后失去可追溯性；持续使用前应安排备份和容量治理。

网页复用现有通用后台任务队列，展示排队、采集、筛选、解读、归档阶段；这些阶段不是耗时百分比或完成时间预测。归档完成不等于来源完整或每个事件解读成功，覆盖卡片另列模型未配置、空内容、超时、调用失败、格式/证据校验失败或遗漏事件等缺口；仅显式抛出 `TimeoutError` 的失败归类为超时，其他提供方错误可能归为调用失败。无材料和筛选后为空单独说明。

原同步 POST 保留兼容。两种入口共用进程内单任务锁（忙时 409）；同请求键同参数复用任务/结果，不同参数拒绝。**本实现面向单进程本地部署**：多 worker 的并发锁和待完成状态不共享，数据库唯一键只防重复归档，不能保证跨进程模型调用只发生一次。运行中的状态暂存在内存，重启不恢复未归档工作；已归档结果可按请求键找回。页面每 1.5 秒查询，最多 400 轮，网络失败停止轮询；会话存储可用时只保存请求键，不保存新闻输入或持仓。刷新/切换市场/断线只停止客户端等待，不取消服务端任务。使用“检查上次任务状态”只读恢复，未知状态先查看历史，不自动重新调用模型；明确失败后须人工重新提交。

“仅重试缺失解读”保留成功解读和冻结证据/代码级持仓，不重新采集，不重读新持仓，不自动重试。追加快照带 `parent_brief_id` 和 `analysis_retried_at`，`captured_at` 仍是原证据采集时间；旧快照、证据时间、原分组均不改写。因此跨日补解读不能当作当日新闻研报，需新生成才重新核验材料。最新人工争议/撤回记录阻止相关缺失解读，页面继续显示核验覆盖层。回滚这一轮时切回原同步 POST 与前端生成流程，保留已追加快照及字段；不涉及账本、订单或调度。

## 验证与回滚

离线测试覆盖：时区/跨日、日期精度、旧/未来新闻、同标题合并但不自动确认、内容修订、核验覆盖层、模型引用和持仓越界、失败披露、幂等 API、真实账本只读重放、页面中英文与异步状态隔离。

2026-09-29 隔离试跑：从三条公开资讯源取得 70 条材料，留存输入后以 v2 规则回放，得到 14 个候选、展示 8 个；45 组未命中主题、10 组未命中市场规则，另有同标题归并，因此筛选计数不能直接当作原始条目之和。人工补充 4 条已查看的官网公告/排期后，得到 18 个候选、仍展示 8 个，旧财报预告能保留为未来事件。该试跑特意混入跨市场来源检验噪声过滤，不等同于生产美股采集入口，也不是自动经济日历接入。

试跑使用临时数据库，没有改动真实持仓或生产资讯源开关。该隔离试跑进程没有配置可用模型，返回 `model_unavailable`，不能据此判断另一台 Windows 正式服务的配置；新闻采集、筛选与归档已验证，但真实模型解读质量与生产端到端运行仍待验收。浏览器验收使用明确标记的合成消息，覆盖桌面/手机布局、排期输入、模型不可用提示，以及撤回后隐藏旧解读；不将合成消息当作财经证据。

### 可选投资档案关联（代码级，非账本导入）

- 在数据源设置中显式配置 `MARKET_EVENT_PROFILE_PATH`，启用前确认允许所选模型接收持仓代码和市场。默认空值关闭；路径按服务进程工作目录解析，跨主机部署须重新配置，不复制本机路径或默认扫描文件。清空该配置即可停止后续档案读取，既有简报快照不被删除。
- 只支持受控 Markdown 格式：一行 `更新日期：YYYY-MM-DD ...`；`## 当前主要持仓` 下首个表格为美股（首列纯代码、第二列“已确认持有份额”）；可选 `### 当前已知人民币资产` 表格首列含唯一六位代码、第二列“持有份额”。到下个标题即停止，不读取历史表、自选、目标或正文指令。数量只用于本地判断零/正持仓，明确“未显示，待确认”等存在性记录也可纳入；未知格式整份停止关联，不猜股数。
- 读取上限 128 KiB；文档日期按北京时间检查，超过 7 天、日期在未来、结构缺失/重复、代码或数量异常时返回独立缺口状态。档案版本日期不是成交、估值或每项资产的确认日期，不证明券商实时持仓。
- 只在数据库没有任何投资账户时使用档案。已有账户即使为空或停用也不从旧档案补仓，以免复活已平仓标的；将来导入账本前须完整核对所有资产，不能把部分账本与档案静默混合。解析不会创建账户、期初余额、交易、现金、预算或持仓缓存。
- 每期只保留对应研究市场的代码（全球简报可保留全部）；境内基金代码归境内产品市场，不自动当作港股代码或可做 T 证券。只向模型发送 `symbol`、`market`；文件全文、路径、数量、金额、成本、账户、角色及历史指令不会进入提示词。新闻中的行业缩写可能与 ETF 代码同名，文本命中仅提高阅读优先级，不能证明直接关联或成分暴露。
- 简报归档保存投影后的关联范围、版本日期和投影摘要值；同一请求重试保留首次快照，不按后续档案改写历史。页面和 Markdown 明示档案口径、过期/错误状态及可能关联；没有关联不代表没有风险。隔离验收命令继续强制空持仓，即使生产配置了此路径也不会读取档案。

### 可重复的隔离验收命令

在实际部署机器的项目根目录、使用运行该服务的 Python 环境执行。`ENV_FILE` 和模型/搜索配置沿用原入口，不复制密钥、不自动换模型；Mac 上运行不能代替 Windows 正式进程验收。

```powershell
# 默认只检查配置和只读资讯源设置，不联网、不调用模型、不初始化生产数据库
python scripts/check_market_events.py --market us

# 明确允许联网及可能计费的模型/搜索调用；仍只写新的隔离数据库
python scripts/check_market_events.py --market us --live --model --search

# 可选：仅检查两条内置模板，不代表生产已启用这些源
python scripts/check_market_events.py --market us --live --model --template global-marketwatch --template newsnow-jin10
```

- 每次创建独立临时目录，或用 `--output-dir` 指定一个**尚不存在**的目录；不覆盖既有数据库或验收结果。整个工作进程默认 180 秒截止，`--timeout-seconds` 可设 10–600 秒，超时终止自己的进程树并记录 `timeout`，不会因已有部分结果而报通过。原生 Windows 的结束进程树分支仍需在正式主机确认。
- 不启动 API、定时器或通知服务。生产数据库只用 SQLite `mode=ro` 读取已启用源配置，最多读取 100 条、按原排序选匹配市场的前 6 条，保留截断状态；不读取/复制生产持仓、金额、成本或缓存新闻。刷新和原始证据归档复用 `MarketEventService.generate`，模型用量也落在隔离库。
- 只有 `--live` 才刷新源；只有额外 `--model` 才请求当前模型、`--search` 才查询已配置搜索渠道。`--template` 显式标记 `template_smoke`，既不修改生产源开关，也不能声称生产采集已通过。
- `acceptance.json` 是可分享的检查摘要，只含配置存在性、匿名源状态、数量、选中证据时间精度、幂等/归档/文本渲染检查等；不输出密钥、源配置 URL、账户或异常原文。`brief.json` / `brief.md` 保存该次取得的公开新闻证据与条件式解读（若可用）。`acceptance.db` 可能包含带认证参数的源地址及模型用量，**请只分享摘要，不上传整个目录或数据库**。
- `preflight_only` 表示只做配置预检，退出码 0 不意味着联网验收完成。完整请求的技术检查全部通过且模型合约通过才返回 `technical_checks_passed` / 0；其余 `incomplete`、`failed`、`worker_failed`、`timeout` 返回 2。源有响应但新闻为空、缺时区、缺模型、模型只完成部分事件、只检查来源未请求模型，都不能算完整通过。
- 预检的 `generation_backend` 展示所选生成路线；`model_route_configured` 识别显式本地 CLI 路线，不要求同时存在 LiteLLM 模型。`model_deployment_count` 仅计 LiteLLM 部署，CLI 下为 0 不代表未配置；这些字段不验证 CLI 登录、网络、额度或真实生成，仍需显式联网模型验收。
- `requested_sources_completed` 仅表示本次请求源没有失败/未配置/截断，不代表全网覆盖；筛选计数保留规则漏报边界。技术通过仍不证明新闻真实、模型推理正确或交易有收益，摘要明确保留人工解读质量、账本对账、生产 HTTP 认证/UI、调度通知、行情/NAV 等未验收项。
- 在 Windows 获得正确配置后，先预检再运行正式配置隔离检查，并人工检查 `brief.md` 的来源、发布/事件时间、条件句与反方情景；不可用模板结果替代正式配置结果，不可用合成测试通过替代真实模型输出检查。

2026-09-30 北京时间 17:16 本机模板试跑：两条公开源响应成功，取得 36 条材料，现有美股规则筛选后保留 1 条，15 组未命中市场、20 组未命中主题。归档往返、请求幂等、文本附录和隔离账本空白检查通过；模型仍为 `model_unavailable`，整体记录 `incomplete`。这不代表当天只有一条重要新闻，也不代表 Windows 正式服务通过；本机预检同时显示未配置模型路线和已启用资讯源。一次性结果保留在仓库外，不合入新闻快照或真实资产数据。

2026-09-30 北京时间 18:44–18:46，本机在显式启用 `codex_cli`、禁用未配置备用路线后完成公开模板 + 真实模型隔离验收：两条源成功取得 40 条材料，筛选 4 个事件，4 条证据均带时区时间戳，模型合约、归档往返、幂等及隔离账本空白等检查全部通过（`technical_checks_passed`，约 98 秒）。此前固定 JSON 的 HTTP 冒烟调用亦通过，设置页确认主路线为 Codex CLI。该次未启用搜索、正式资讯源、调度或通知，未复制持仓；人工抽查输出保留来源待核验、条件式传导与反方情景，但不代表新闻真实性、全市场覆盖、模型推理质量或生产个性化研报已验收。临时结果仍留在仓库外。切回“设置 → AI 模型 → 分析生成方式 → 默认模型配置”可停用 CLI 路线；原 API 模型未配置时不能据此获得可用备用模型。

2026-09-30 北京时间 19:59 本机服务入口验收：在 Mac 本地库启用已验证的 MarketWatch、NewsNow 金十这两条源，刷新后资讯池保留 69 条材料，筛选 8 个事件；真实模型返回 5 条合规解读，3 条未完成，快照 #1 明确记录 `partial_analysis`，不认定为完整模型验收通过。已在页面核验来源状态、历史快照和部分解读提示。投资档案关联仍留空，等待用户确认代码/市场向模型传输；仅本地解析核验，不外发持仓、不建交易账本。140 项后端及 12 项页面测试、lint、前端构建通过；券商同步、Windows 正式进程及个性化真实模型结果仍未验收。

2026-09-30 用户明确确认代码/市场向当前模型传输后，本机通过版本化配置 API 单独开启档案路径，未改变生成路线或调度。北京时间 20:18:20 留存个性化快照 #2，真实生成约 186 秒：两条源刷新成功，资讯池 69 条，筛选 8 个事件，7 个完成合规解读、1 个未返回解读，仍为 `partial_analysis`，不宣称完整验收通过。归档及页面显示档案日期 2026-09-29 和 5 个美股代码，模型关联未越出本期集合；该日期不是成交或估值日期。本轮再次通过 17 项档案测试、54 项新闻服务测试；交易账户、成交及持仓缓存仍各为零，调度仍禁用。只验证本机代码级个性化链路，未核验全部新闻原文、实时行情、券商持仓或 Windows 正式进程。

回滚：本轮资讯源可在“资讯源设置”取消启用，档案路径留空可关闭关联，均保留历史快照。若撤回整个功能，移除市场事件路由、页面及大盘附录接入，恢复此次代码改动；**保留新增表及其归档数据**。不需要删除账本、改变持仓或撤销任何成交。本功能不新增调度或下单通道，因此没有需要停用的自动交易任务。

## English summary

### 2026-10-08：持仓外热点及覆盖复盘

- CN/HK 跨行业扫描由三组变为五组（另加原有两组市场新闻），增加电池/固态电池/储能及不受固定行业表限制的热点轮动检索；US 保留三组并加入电池储能词。不开启搜索/扫描就不产生相应新增请求。单查询12秒限制沿用，搜索供应商可能计费。
- A股/港股大盘日报复用行业查询；单条失败继续后续查询。模型新闻上下文改为去重、优先不同板块的最多12条，仍非全市场覆盖。现有行业/概念涨跌榜保持原数据源，不将搜索新闻当实时行情。
- 新快照额外保存 `candidate_events`，包含时间/市场/主题过滤后的全部有界候选，不受正文8条及每主题条数限制。新闻雷达据此展示漏选线索及原文；模型仍只解读正文8条。旧快照缺该字段时回退到正文，不重构过去。
- `coverage_audit` 在生成时冻结，取同市场本地日首份原始快照（排除补解读版本）为基线。基线缺候选池则显示无可比基线；不跨日比较，不读取未来快照。仅比较行业是否出现，并非同事件新颖度、盘前命中率、买点状态或交易盈亏。撤回核验会降级当前雷达，不改写历史覆盖事实。
- 页面加载不启动扫描；本次没有新增排程、实时盘口监控、券商调用或自动交易。聊天中的早报没有自动入本地库，不能用新结果补造今天09:13的基线。
- 回滚：撤回本节对应候选池/对照/检索接入改动，保留数据库与旧JSON；无需迁移或删除任何表、持仓或历史快照。

CN/HK now add five bounded sector/theme searches including batteries/storage and open-ended market rotation; US retains three. Market-review prompts diversify up to 12 news items and isolate individual search failures. New snapshots retain pre-selection candidates; legacy snapshots fall back to selected events. Frozen same-day coverage comparisons exclude interpretation retries and never infer tradability, trigger success or missed profit. No calendar, order, real-time quote or notification changes. Roll back code only, preserving archives and all portfolio data.

The web client now submits to `/market-events/jobs` and polls real shared-queue stages. Archival completion is distinct from complete evidence/model coverage. Missing-only retries explicitly incur possible model charges, append a linked snapshot, and preserve original evidence dates, holding symbols and successful interpretations. They do not refresh news or turn old evidence into today's report. No automatic retry occurs. Polling disconnects do not cancel server work; session storage keeps only the request key for read-only recovery. Completed archives survive restarts, but pending state is in memory. This is a single-process local workflow: multi-worker locks/status are not shared and durable unique keys do not guarantee exactly-once model invocation across workers. The original synchronous API stays compatible; rollback can restore that client path while retaining all archives.

Market events is a source-backed research page, not a trading engine. Generate explicitly using configured search, optionally refresh enabled feeds, and optionally call the existing model. Visiting history does not trigger collection. Source claims remain reported/unverified; known official domains do not auto-certify a claim. Human verification requires a supporting/correction URL and a note, and is append-only.

Evidence versions and reports are immutable. Publication, occurrence and first-observed times are distinct. Naive/unknown dates are not promoted to intraday facts. Exact-title/date deduplication is conservative; syndicated copies are not independent corroboration. Reports select at most eight events with transparent reading-priority heuristics, never win probabilities. Model citations and holding identities are validated against the supplied snapshot; interpretation is still explicitly an AI hypothesis.

Version 2 filters by financial topics and target-market relevance, with English word boundaries and explicit exclusion counts. Topic caps prevent foreign-policy headlines from occupying every slot. Known official-domain links raise reading priority, not verification status. Explicit occurrences within the next seven days preserve older notices as upcoming events, never as published results. This is not an automatic economic-calendar feed; unmatched topics can still matter and need editorial review. Model availability is shown separately from source connectivity.

The model sees up to three evidence items per event, preferring official-domain links without certifying them. Other collected evidence remains in the archive and page; citations to omitted items are rejected.

Holdings default to read-only quantity replay of recorded ledger events, never watchlists or broker synchronization. If no portfolio accounts exist, an explicitly configured `MARKET_EVENT_PROFILE_PATH` may supply a code-only reference after the user consents to sharing symbols and markets with the selected model. Any ledger account, even empty or inactive, prevents this fallback. Only the documented current-holdings tables are parsed; stale (over seven days), future-dated or invalid profiles stop linkage. No quantities, costs, account balances, file paths or profile prose are sent to the model. The reference date and basis are visible and do not prove current broker positions. Clear the setting to stop future profile reads while preserving archived briefs. Unknown holdings remain unknown. No orders, signals, executable prices, NAV claims or performance guarantees are generated.

Existing CN/HK/US market reviews append a frozen evidence section using the news they already collected, with no additional search/model call or notification schedule. The web page can request richer model interpretation separately. Rollback the code and keep the three new archival tables; existing portfolio and trade data remain untouched. Live source availability and model reasoning quality require deployment-environment verification beyond deterministic tests.

The isolated September 29, 2026 trial replayed 70 retained live items from three public feeds: 14 candidates, eight selected. Four manually reviewed primary notices increased candidates to 18, still selecting eight. Cross-market input was intentional stress testing, not the production US collector or an automatic calendar feed. That isolated process had no configured model and correctly reported `model_unavailable`; this does not establish the configuration of a separate Windows service. Live model quality and production end-to-end acceptance remain unverified. Browser checks use clearly labelled synthetic news, not investment evidence.

`python scripts/check_market_events.py --market us` performs offline preflight only. On the actual deployment host, add `--live --model --search` to explicitly authorize news/model/search requests (provider charges may apply). It reads production source settings through SQLite read-only mode, never copies portfolio data, and writes news plus model usage only to a fresh private scratch database. `--template` is explicitly a template smoke, not production acceptance. A hard worker deadline records timeout rather than success. Share only `acceptance.json`; the scratch database may contain sensitive source URLs. `technical_checks_passed` certifies structural checks only, not source truth, model reasoning quality, HTTP/UI, scheduling, portfolio reconciliation or trading suitability. Native Windows process-tree termination still needs host verification.

The September 30 local template smoke fetched 36 items from two responding public feeds and selected one under the existing US rules. Archival roundtrip, retry idempotency and text rendering passed, but no model route was configured: the overall result remained `incomplete`. This is not a claim of exhaustive news coverage or production readiness. To roll back this diagnostic addition, remove the standalone script; keep private diagnostic evidence as needed and leave all production data untouched.

After explicit consent, the September 30 20:18 BJT local personalized run enabled only the profile-path setting and used the existing model route. Both feeds refreshed successfully; the 69-item pool yielded eight selected events and seven valid interpretations in about 186 seconds. Snapshot #2 remains `partial_analysis`, not a complete model acceptance pass. Its five US reference symbols and profile date were verified in the archive and UI, with no out-of-scope model holding links. The 17 profile and 54 news-service tests passed again; account, trade and position tables stayed empty and scheduling stayed disabled. Source truth, market data, broker reconciliation and the separate Windows deployment remain outside this check.
