# TripTonic

**TripTonic** 是一个研究型旅游规划 Agent Skill：先用 OpenCLI 研究小红书真实体验，再结合同行人画像做路线取舍，最后通过本地脚本校验结构化行程并生成可离线阅读的攻略文件。

## 工作原理

1. **环境检查**：确认 OpenCLI、Browser Bridge 扩展与小红书登录状态。
2. **研究**：用 OpenCLI 的搜索/笔记/评论能力收集体验证据，登记来源与时效（见 `references/opencli-research.md`）。
3. **记录**：把检索、深读笔记、证据卡与决策写入研究记录，用 `lint-research` 检查覆盖度。
4. **画像筛选**：按年龄、体力、预算、饮食与兴趣对候选做分级取舍（见 `references/user-profile.md`）。
5. **结构化**：产出 `guide.json`，运行 `validate` 检查结构、来源、日期、时间与交通。
6. **构建**：运行 `build` 生成 7 个离线产物；`serve` 可本地预览并自动重建。

## 功能特性

### 研究与记录

- 小红书搜索/笔记/评论收集体验证据，保留来源与时效；研究阶段采集笔记的图片/视频链接（`sources[].media`）——适配器不返回媒体字段时按 `references/opencli-research.md` 的浏览器回退方案从笔记页提取（`__INITIAL_STATE__`，每篇至多前 4 张）。
- `lint-research` 按 JSON schema 检查研究记录结构与缺口登记；覆盖阈值按行程天数分档：

  | 行程长度 | 检索次数 | 深读笔记 | 评论串 | 主题轴 |
  | --- | --- | --- | --- | --- |
  | 1–3 天 | 4 | 6 | 3 | 4 |
  | 4–7 天 | 6 | 8 | 4 | 5 |
  | 8 天以上 | 8 | 10 | 5 | 6 |

  强制 7 类检索主题矩阵（行程/景点/美食/住宿/交通/时效/避坑）与时效过滤记录，`--strict` 下警告即失败。

### 校验

- JSON Schema 子集校验 + 业务校验；严格 JSON 解析，重复键直接报错。
- 来源引用、日期序列、时间重叠（冲突）、接驳缓冲（冲突）、住宿连续性、次日首站接驳。
- 节奏与同行人适配：`preferences.pace` 对照每日时间跨度与活动项数（PACE_OVERLOAD）、时间窗（TIME_WINDOW）、自驾疲劳（DRIVE_FATIGUE）。
- 预算一致性（合计 vs 分项）；住宿/餐饮/商家核实超期（30/30/30 天）与来源超期（180 天）警告；避坑条目缺 `wrong`+`right` 或 `name`+`reason` 时 AVOID_STRUCTURE 警告（两种写法渲染均支持）。
- 交通 `mode` 规范化（自驾/开车 → drive、火车 → train 等），未识别时给出带建议的警告。
- 媒体链接结构校验（type 枚举 + HTTP(S) URL）；签名链接来源核实超 14 天触发 MEDIA_STALE 警告。

### 渲染与产物

- 自包含 HTML（含打印样式按天分页）与 Markdown；正文完整双语（`meta.language` 以 `en` 开头切英文，校验报告保持中文）。
- 行程统计小节（天数/活动项/餐饮/自驾时长与里程/最长单段/节奏评估）+ SVG 甘特图 + 预算饼图。
- 路线示意：停靠点坐标齐全时按坐标比例绘制（等距圆柱投影，标注非导航），否则回退非比例链式示意。
- 媒体卡片与相册：`sources[].media` 渲染为可点击卡片；`fetch-media` 把图片/视频下载到本地缓存后，`build --media-cache` 把命中条目渲染为相册（点击开灯箱翻页/播放，Esc/方向键导航），未命中保持链接卡片回退。图片内嵌 data URI、视频拷贝到产物 `media/` 目录，离线可看不受签名链接过期影响；版权归原作者，仅供个人参考。
- 本地图片白名单校验（路径逃逸/魔数/大小）后内嵌为 data URI；视觉层 = 本地图片 + 媒体相册，两者皆无时保持纯文字（不再生成示意插画）。
- `build --online-map` 可选嵌入 Leaflet 在线地图（CDN，需联网）；默认完全离线。
- ICS 日历（浮动本地时间 + DTSTAMP + 交通项 30 分钟提醒 + 清单全天事件）、GeoJSON（有效坐标点 + 有序路线连线 + bbox）、KML（Google Earth）、规范化 JSON（统一键序补编号，便于 diff）。

### 辅助命令

- `init`：从模板生成多日脚手架（自动填日期与天数编号）。
- `compare`：结构差异 + 逐日语义 diff（增删/时间变更）+ 取舍提示（节奏、自驾负担、待核实项数量）。
- `migrate`：显式 `--target` 的 schema 版本迁移链。
- `fetch-media`：把 `sources[].media` 的远端链接下载到本地缓存（幂等可重跑；魔数校验防 HTML 错误页，图片 10MB/视频 200MB 上限；签名链接 403 属预期，失败条目保持链接卡片）。默认缓存目录为 guide JSON 同级的 `media-cache/`。
- `serve`：本地预览，guide.json 保存后自动重建。
- 文本产物全平台 LF 换行；Windows 控制台强制 UTF-8 输出；产物原子替换（先暂存后统一替换，失败保留旧文件）。

当前版本不自动订票、不购买、不执行小红书点赞/收藏/关注/发布，也不声称提供实时票价、天气或交通数据。

## 环境要求

1. OpenCLI 可执行：`opencli --version`。桌面版从 <https://opencli.info/download> 安装；CLI 版要求 Node.js `>=20.18.1`，`npm install -g @jackwener/opencli`。
2. Chrome 已启动，OpenCLI Browser Bridge 扩展已启用，`opencli doctor` 显示桥接已连接。
3. 小红书登录由用户本人完成：`opencli xiaohongshu login --timeout 300 -f json`，再用 `opencli xiaohongshu whoami -f json` 确认。
4. Python `>=3.8`（仅标准库）。

## 快速开始

在 Agent 中加载本目录的 `SKILL.md`：

```text
帮我做一份西藏7天攻略：拉萨往返，第一次去，2位大人和1位65岁老人，节奏适中。
参考小红书真实体验，生成可以离线打开的攻略文件。
```

Agent 按安装检查 → 浏览器桥接 → 用户登录 → 搜索研究 → 证据整理 → 画像筛选 → 结构化校验 → 产物构建的顺序执行。

手动构建：把 `examples/tibet-7-days.json` 复制到输出目录并按真实研究结果填写，然后：

```bash
python scripts/trip_tonic.py validate examples/tibet-7-days.json
python scripts/trip_tonic.py build examples/tibet-7-days.json --output-dir generated/tibet-7-days
# 媒体本地化（可选）：先下载缓存，再构建相册
python scripts/trip_tonic.py fetch-media examples/tibet-7-days.json --cache-dir generated/tibet-7-days-cache
python scripts/trip_tonic.py build examples/tibet-7-days.json --output-dir generated/tibet-7-days --media-cache generated/tibet-7-days-cache
```

## 本地命令

| 命令 | 说明 | 常用参数 |
| --- | --- | --- |
| `validate <input>` | 校验 guide JSON | `--strict`（警告即失败）、`--today YYYY-MM-DD` |
| `build <input>` | 生成全部产物 | `--output-dir`（必填）、`--media-root`、`--media-cache`、`--online-map`、`--strict`、`--today` |
| `init <目录>` | 生成 guide.json 脚手架 | `--title` `--destination` `--origin` `--travelers` `--pace` `--days` `--start-date` `--force` |
| `compare <left> <right>` | 结构化对比两份行程 | — |
| `migrate <input>` | 升级 schema_version | `--target`（默认 1.0） |
| `lint-research <input>` | 校验研究记录 | `--strict` |
| `fetch-media <input>` | 下载媒体到本地缓存 | `--cache-dir`、`--timeout`（默认 30 秒） |
| `serve <input>` | 本地预览 + 自动重建 | `--output-dir`（必填）、`--port`（传 0 自动分配）、`--media-cache`、`--no-watch`、`--strict` |

所有命令输出单行 JSON，便于上层 Agent 解析。

## guide.json 结构要点

- `route.overview` + 有序 `stops` + 逐段 `legs`（方式/时长/距离；区间用 `duration_text`，估算标 `estimated`，自驾段缺数据会警告）。
- `days[].items[]`：时间窗、坐标、`route_from_previous` 接驳缓冲、`backup` 备选（含触发条件）、`source_ids`。
- 住宿/餐饮/商家推荐记录名称、适配理由、核查日期与来源；`checklist` 带日期项导出为 ICS 全天事件；`evidence` 证据卡。
- `sources[].media`：研究采集的图片/视频链接（`type: image|video`、HTTP(S) `url`、`description`）；guide JSON 只存原始 URL 保持研究数据纯度，本地缓存状态由 `fetch-media` 写入缓存目录的 `media-cache.json` 清单，`build --media-cache` 按清单解析相册。
- `images` 指向本地许可素材；视觉层优先级：本地图片 > `sources[].media` 媒体相册 > 纯文字。
- 完整字段定义见 `references/guide-schema.json`（含 `backup`、`checklist`、`evidence`、`media`）。

## 输出产物

构建成功后生成 7 个文件：

```text
guide.html              自包含离线 HTML（打印样式按天分页；启用媒体缓存时相册图片内嵌）
guide.md                Markdown
guide.ics               日历（浮动本地时间，交通项 30 分钟提醒）
guide.geojson           有效坐标点 + 路线连线 + bbox
guide.kml               Google Earth 可导入
guide.normalized.json   规范键序 + 补编号，便于 diff
validation.json         校验报告快照
```

启用 `--media-cache` 且有视频命中缓存时，额外生成 `media/` 子目录（保存攻略时连同一起拷贝，否则视频无法播放）。

脚本仅处理已提供的结构化数据：不抓取小红书，`fetch-media` 只下载 guide 里已登记的媒体链接（原文页面内容不解析），不编造路线事实。待核实与警告会同时渲染进产物，不只留在控制台。

## 参考文件

- `references/opencli-research.md` — 小红书研究流程（搜索/笔记/评论、时效过滤、节流）
- `references/user-profile.md` — 同行人画像与取舍规则
- `references/guide-schema.json` — guide JSON schema
- `references/research-record-schema.json` — 研究记录 JSON schema
- `references/research-record-template.json` / `.md` — 研究记录模板（JSON / Markdown）
- `examples/guide-template.json` — 空白攻略模板（init 的底稿）
- `examples/tibet-7-days.json` — 示例攻略（含媒体链接演示）
- `examples/research-record.example.json` — 可通过 `lint-research --strict` 的虚构示例

模板与示例均为虚构演示，不是小红书真实资料，不能当作来源或推荐使用。

## 开发与测试

```bash
python -m unittest discover -s tests   # 51 个测试
```

CI 配置见 `.github/workflows/ci.yml`（Python 3.8/3.10/3.12 × ubuntu/windows，lint-research 步骤与产物上传）。
