# TripTonic

把小红书真实体验，变成一份**可离线阅读、来源可追溯、为同行人定制**的攻略包。

```text
你说：  帮我做一份西藏7天攻略，2大1小带65岁老人，节奏适中，参考小红书真实体验
得到：  guide.html（离线单文件）+ guide.md + 日历 + 地图 + 校验报告
        每条推荐都带来源回链，不确定的地方明写"待核实"，绝不编造
```

**7 个离线产物 · 53 项自动化测试 · 中英双语 · 纯标准库 Python**

## 为什么用它

- **AI 攻略的三大通病，它都不犯。** 通用 AI 写攻略靠幻觉补细节，TripTonic 只用研究时真实读到的小红书笔记做证据；每条推荐可回链原帖，日期、时间、接驳、预算全过结构化校验，待核实项直接渲染进成品而不是藏起来。
- **它按"你们这一行人"取舍，而不是按热度排名。** 65 岁老人同行就砍掉高海拔徒步；带娃就压缩单日时间跨度；预算档位、饮食限制、体力节奏都会改变取舍结果，理由写在攻略里。
- **产物是文件，不是聊天记录。** 单文件 HTML 带甘特图、预算饼图、按笔记分组的媒体相册（点击开灯箱翻页）；ICS 直接进手机日历（交通项提前 30 分钟提醒）；KML 可导入 Google Earth。发家人、打印、飞机上离线看，都行。
- **默认完全离线。** 图表内联 SVG、图片 data URI 内嵌、无 CDN 无外链（可选 `--online-map` 才联网），攻略不会因为签名链接过期而变成一堆裂图。

## 快速开始（有 Agent）

把本目录装进你的 CLI（见下一节），然后一句话：

```text
帮我做一份西藏7天攻略：拉萨往返，第一次去，2位大人和1位65岁老人，
节奏适中。参考小红书真实体验，生成可以离线打开的攻略文件。
```

Agent 按安装检查 → 浏览器桥接 → 小红书登录 → 搜索研究 → 证据整理 → 画像取舍 → 结构化校验 → 产物构建的顺序执行，全程不用你操心命令。

## 接入不同 CLI

本 skill 是标准 [Agent Skills](https://opencode.ai/docs/skills/) 格式（`SKILL.md` + YAML frontmatter），目录名须保持 `trip-tonic`。

### Claude Code（原生支持）

```bash
# 个人全局：所有项目可用
git clone https://github.com/<you>/trip-tonic ~/.claude/skills/trip-tonic
# 或项目级：仅当前项目可用
mkdir -p .claude/skills && cp -r /path/to/trip-tonic .claude/skills/trip-tonic
```

Windows（PowerShell）把 `~` 换成 `"$env:USERPROFILE"`。之后在对话里直接提旅行规划，Claude 按 skill 描述自动加载。

### opencode（原生支持）

```bash
# 全局
git clone https://github.com/<you>/trip-tonic ~/.config/opencode/skills/trip-tonic
# 或项目级
mkdir -p .opencode/skills && cp -r /path/to/trip-tonic .opencode/skills/trip-tonic
```

opencode 也会发现 Claude 兼容路径（`~/.claude/skills/`、`.claude/skills/`、`.agents/skills/`）——**装一份 `~/.claude/skills/`，Claude Code 和 opencode 同时可用**。需要审批加载可在 `opencode.json` 里用 `permission.skill` 配置。

### Codex CLI / Gemini CLI / 任意读 AGENTS.md 的 Agent

这类 CLI 没有 skill 机制，但都能读上下文文件。把仓库放进项目，在 `AGENTS.md`（Gemini 用 `GEMINI.md`）加一段：

```markdown
## Travel planning
For any trip planning, itinerary or travel-research request, read and
follow `trip-tonic/SKILL.md` (Agent Skill). Run its scripts via
`python trip-tonic/scripts/trip_tonic.py <command>`.
```

### 不用 Agent：纯命令行

研究层自己用 OpenCLI 完成（见 `references/opencli-research.md`），手工填写 `guide.json` 后：

```bash
python scripts/trip_tonic.py validate my-guide.json
python scripts/trip_tonic.py build my-guide.json --output-dir output/my-trip
# 媒体本地化（可选）：先下载缓存，再构建分组相册
python scripts/trip_tonic.py fetch-media my-guide.json --cache-dir output/my-trip-cache
python scripts/trip_tonic.py build my-guide.json --output-dir output/my-trip --media-cache output/my-trip-cache
python scripts/trip_tonic.py serve my-guide.json --output-dir output/my-trip   # 本地预览+自动重建
```

## 环境要求

1. OpenCLI 可执行：`opencli --version`。桌面版从 <https://opencli.info/download> 安装；CLI 版要求 Node.js `>=20.18.1`，`npm install -g @jackwener/opencli`。
2. Chrome 已启动，OpenCLI Browser Bridge 扩展已启用，`opencli doctor` 显示桥接已连接。
3. 小红书登录由用户本人完成：`opencli xiaohongshu login --timeout 300 -f json`，再 `opencli xiaohongshu whoami -f json` 确认。
4. Python `>=3.8`（仅标准库，无需 pip 安装任何东西）。

## 工作原理

1. **环境检查**：确认 OpenCLI、Browser Bridge 扩展与小红书登录状态。
2. **研究**：用 OpenCLI 的搜索/笔记/评论能力收集体验证据，登记来源与时效（见 `references/opencli-research.md`）；同时采集笔记图片/视频链接（`sources[].media`），适配器不返回媒体字段时按浏览器回退方案从笔记页提取。
3. **记录**：检索、深读笔记、证据卡与决策写入研究记录，`lint-research` 检查覆盖度。
4. **画像筛选**：按年龄、体力、预算、饮食与兴趣对候选做分级取舍（见 `references/user-profile.md`）。
5. **结构化**：产出 `guide.json`，`validate` 检查结构、来源、日期、时间与交通。
6. **构建**：`build` 生成 7 个离线产物；`serve` 本地预览并自动重建。

## 校验能力（为什么可以信它）

- 严格 JSON 解析（重复键报错）+ JSON Schema 子集校验。
- 来源引用、日期序列、时间重叠（记为冲突）、接驳缓冲（记为冲突）、住宿连续性、次日首站接驳。
- 节奏与同行人适配：`preferences.pace` 对照每日时间跨度与活动项数（PACE_OVERLOAD）、时间窗（TIME_WINDOW）、自驾疲劳（DRIVE_FATIGUE）。
- 预算一致性（合计 vs 分项）；住宿/餐饮/商家核实超期（30 天）与来源超期（180 天）警告；避坑条目缺 `wrong`+`right` 或 `name`+`reason` 时 AVOID_STRUCTURE 警告（两种写法渲染均支持）。
- 交通 `mode` 规范化（自驾/开车 → drive、火车 → train 等）；媒体链接结构校验 + 签名链接超 14 天触发 MEDIA_STALE 警告。
- 研究覆盖度门槛按行程天数分档：

  | 行程长度 | 检索次数 | 深读笔记 | 评论串 | 主题轴 |
  | --- | --- | --- | --- | --- |
  | 1–3 天 | 4 | 6 | 3 | 4 |
  | 4–7 天 | 6 | 8 | 4 | 5 |
  | 8 天以上 | 8 | 10 | 5 | 6 |

  强制 7 类检索主题矩阵（行程/景点/美食/住宿/交通/时效/避坑），`--strict` 下警告即失败。

## 本地命令

| 命令 | 说明 | 常用参数 |
| --- | --- | --- |
| `validate <input>` | 校验 guide JSON | `--strict`、`--today YYYY-MM-DD` |
| `build <input>` | 生成全部产物 | `--output-dir`（必填）、`--media-cache`、`--media-root`、`--online-map`、`--strict`、`--today` |
| `init <目录>` | 生成 guide.json 脚手架 | `--title` `--destination` `--origin` `--travelers` `--pace` `--days` `--start-date` `--force` |
| `compare <left> <right>` | 结构化对比两份行程 | — |
| `migrate <input>` | 升级 schema_version | `--target`（默认 1.0） |
| `lint-research <input>` | 校验研究记录 | `--strict` |
| `fetch-media <input>` | 下载媒体到本地缓存 | `--cache-dir`、`--timeout`（默认 30 秒） |
| `serve <input>` | 本地预览 + 自动重建 | `--output-dir`（必填）、`--port`、`--media-cache`、`--no-watch`、`--strict` |

所有命令输出单行 JSON，便于上层 Agent 解析。`compare` 能给出两份行程的语义 diff 与取舍提示（节奏、自驾负担、待核实项数量）；`fetch-media` 幂等可重跑，魔数校验防 HTML 错误页，图片 10MB/视频 200MB 上限。

## 渲染与产物

构建成功后生成 7 个文件：

```text
guide.html              自包含离线 HTML（打印样式按天分页；媒体相册图片内嵌）
guide.md                Markdown
guide.ics               日历（浮动本地时间，交通项 30 分钟提醒，清单项全天事件）
guide.geojson           有效坐标点 + 有序路线连线 + bbox
guide.kml               Google Earth 可导入
guide.normalized.json   规范键序 + 补编号，便于 diff
validation.json         校验报告快照
```

- **媒体相册**：`sources[].media` 经 `fetch-media` 本地化后按笔记分组渲染——卡片上图下文说明，点击开灯箱组内循环翻页，Esc/方向键导航，分组头保留笔记回链；媒体多时默认折叠（前 3 组、每组前 4 张），分区头部与底部各有一个「查看更多/收起」按钮（状态同步），单张图片不会被拉伸占满整行。未命中缓存的条目回退为链接卡片。图片内嵌 data URI、视频拷贝到产物 `media/` 目录（迁移攻略时连同拷贝），版权归原作者，仅供个人参考。
- **行程统计**：天数/活动项/餐饮/自驾时长与里程/最长单段/节奏评估 + SVG 甘特图 + 预算饼图。
- **路线示意**：停靠点坐标齐全时按坐标比例绘制（标注非导航），否则回退非比例链式示意。
- **双语**：`meta.language` 以 `en` 开头全文切英文（校验报告保持中文）。
- 文本产物全平台 LF 换行；Windows 控制台强制 UTF-8 输出；产物原子替换（失败保留旧文件）。

## guide.json 结构要点

- `route.overview` + 有序 `stops` + 逐段 `legs`（方式/时长/距离；区间用 `duration_text`，估算标 `estimated`，自驾段缺数据会警告）。
- `days[].items[]`：时间窗、坐标、`route_from_previous` 接驳缓冲、`backup` 备选（含触发条件）、`source_ids`。
- 住宿/餐饮/商家推荐记录名称、适配理由、核查日期与来源；`evidence` 证据卡保留分歧与置信度。
- `sources[].media`：研究采集的图片/视频链接（`type: image|video`、HTTP(S) `url`、`description`）；guide JSON 只存原始 URL 保持研究数据纯度，缓存状态由 `media-cache.json` 清单管理。
- `images` 指向本地许可素材；视觉层优先级：本地图片 > `sources[].media` 媒体相册 > 纯文字。
- 完整字段定义见 `references/guide-schema.json`。

## 诚实边界

当前版本不自动订票、不购买、不执行小红书点赞/收藏/关注/发布，也不声称提供实时票价、天气或交通数据。脚本仅处理已提供的结构化数据：不抓取小红书，`fetch-media` 只下载 guide 里已登记的媒体链接，不编造路线事实。待核实与警告会同时渲染进产物，不只留在控制台。

## 参考文件

- `references/opencli-research.md` — 小红书研究流程（搜索/笔记/评论、时效过滤、节流、媒体回退提取）
- `references/user-profile.md` — 同行人画像与取舍规则
- `references/guide-schema.json` / `references/research-record-schema.json` — JSON schema
- `references/research-record-template.json` / `.md` — 研究记录模板
- `examples/guide-template.json` — 空白攻略模板（init 的底稿）
- `examples/tibet-7-days.json` — 示例攻略（含媒体链接演示）
- `examples/research-record.example.json` — 可通过 `lint-research --strict` 的虚构示例

模板与示例均为虚构演示，不是小红书真实资料，不能当作来源或推荐使用。

## 开发与测试

```bash
python -m unittest discover -s tests   # 53 个测试
```

CI 配置见 `.github/workflows/ci.yml`（Python 3.8/3.10/3.12 × ubuntu/windows，lint-research 步骤与产物上传）。
