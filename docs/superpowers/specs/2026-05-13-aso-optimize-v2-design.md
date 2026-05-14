# ASO 优化 v2 — 设计 spec

**Date**: 2026-05-13
**Status**: Approved, ready for `writing-plans`
**Replaces / Iterates on**: `aso_daily.py`（保留作为日报，本工具是按需深度优化）

---

## 1. Background

我们已有 `aso_daily.py`（按 30 日下载量自动取 top-3 app，每个出一份 ASO 监控日报）。本工具与之**不同的定位**：

| | aso_daily（已有） | aso_optimize v2（本 spec） |
|---|---|---|
| 触发方式 | 跑一次给所有人看 | 按需指定单个 app |
| 目的 | 监控变化 | 生成优化建议 |
| 输出 | rank/pop/diff 表 | **新的 title/subtitle/keywords 字符串** |
| LLM | 不用 | 全程用（Claude 在对话里） |
| 数据范围 | rank ≤ 20 才进表 | 全部 token 都查 |
| 迭代 | 否 | 可来回多轮（满意/不满意） |

---

## 2. Goal

给定单个 app，生成可直接粘贴到 App Store Connect 的**新的主标题、副标题、关键词字段**字符串，每个字段附 rationale。

---

## 3. High-level architecture

```
┌──────────────────────────────────────────────┐
│  Python 脚本 aso_optimize.py（数据层）          │
│  · 加载 apps_full.json / sales_cache          │
│  · iTunes Search 排名查询                      │
│  · Astro popularity / difficulty 查询          │
│  · 输出中间 JSON（phase_a / phase_b）            │
└──────────────────┬───────────────────────────┘
                   │ (intermediate JSON)
                   ▼
┌──────────────────────────────────────────────┐
│  Claude（对话层）= LLM 全部任务承担方            │
│  · 读 JSON + ASO_methodology.txt 相关章节       │
│  · Phase B Step 1：生成 10-15 候选词 + 理由     │
│  · Phase B Step 3：把验证后的候选词展示给用户     │
│  · 用户说"再来一批" → goto B1                   │
│  · Phase C：合成新 metadata 三段字符串           │
└──────────────────────────────────────────────┘
```

---

## 4. Phase A — 现状分析（脚本）

### Trigger
```bash
python3 aso_optimize.py analyze <app>
```

`<app>` 接受：
- App Store ID（如 `1482080766`）
- bundle ID（如 `com.fengyiqi.PostItnoteForMac`）
- SKU
- app name 模糊匹配（"sticky note" → "Sticky Note Pro: Post-it&Memo"）

### 处理步骤
1. 在 `apps_full.json` 里定位该 app
2. 由 `sales_cache.json` 算近 30 日按 country 拆分的下载量 → 取主市场
3. 用 `pick_locales_for_country` 选 locale（沿用 aso_optimize.py 现有逻辑）
4. 从 metadata 抽 `title / subtitle / keywords`
5. `tokenize_text(title, subtitle, keywords)`（沿用现有逻辑，含 CJK ≥ 6 字符过滤、stopword 过滤）
6. **对每个 token 都跑** `itunes_rank()` —— **不再用 rank ≤ 20 过滤**，rank=null 也保留
7. `astro_client.lookup_popularity_batch()` 查每个 token 的 pop + diff（已缓存的不再消耗 Astro 槽位）
8. 写 `phase_a_<app_slug>.json`

### Phase A JSON 形态
```json
{
  "app": "GBrowser:Choose Link Openly",
  "app_id": "6737885863",
  "bundle_id": "com.soloware.opnelink",
  "platform": "macOS",
  "market": "CN",
  "locale": "zh-Hans",
  "downloads_30d_in_market": 25147,
  "current_metadata": {
    "title": "GBrowser:Choose Link Openly",
    "subtitle": "Any link in any browser浏览器下载",
    "keywords": "谷歌浏览器,chrome,..."
  },
  "current_tokens": [
    {
      "keyword": "谷歌浏览器",
      "source": ["K"],
      "rank": 1,
      "popularity": 82,
      "difficulty": 77
    },
    {
      "keyword": "MacOS",
      "source": ["K"],
      "rank": null,
      "popularity": 5,
      "difficulty": 80
    }
  ],
  "generated_at": "2026-05-13T12:34:00+08:00"
}
```

---

## 5. Phase B — 候选词生成 + 验证

### B1 — 我（Claude）生成候选词
- **输入**: Phase A JSON + `ASO_methodology.txt`（重点章节：§5.3 / §6.2 / §7.3 / §10.1 / §10.4 / §2.4）+ 历史被拒绝候选词（迭代时）
- **输出**: 10–15 个候选词清单，每个带：
  - 词
  - 类型（同义词扩展 / 长尾组合 / 上位词 / 拼写变体 / 品牌词联想 / 行业词等）
  - 为什么推荐（基于现有数据 + 方法论）

### B2 — 脚本验证
```bash
python3 aso_optimize.py validate <app> --candidates kw1,kw2,kw3,...
```
- iTunes rank + Astro pop/diff 一次性查
- 写 `phase_b_<app_slug>.json`

### Phase B JSON 形态
```json
{
  "app_id": "6737885863",
  "market": "CN",
  "candidates": [
    {
      "keyword": "谷歌地图",
      "rank": 2,
      "popularity": 74,
      "difficulty": 25
    },
    {
      "keyword": "翻译",
      "rank": null,
      "popularity": 75,
      "difficulty": 76
    }
  ],
  "generated_at": "2026-05-13T12:40:00+08:00"
}
```

### B3 — 我（Claude）展示 + 用户审核
我把候选词排版展示，标注每个的诊断（如"高 pop 低 diff 强烈推荐"/"已偶然命中 #2 可主动收编"/"难度过高待观察"），等用户响应：

| 用户响应 | 行为 |
|---|---|
| 👍 / "都要" / "接受全部" | 全部进入 Phase C |
| 👎 / "再来一批" | 记录这批为已拒绝，回 B1 重新生成 |
| ✏ / "只要 1/3/5"（数字） | 只保留指定的，剩余的进 B1 让我再生成补够 |
| "去掉 X 加 Y" | 部分修订后进 Phase C |

迭代上限：3 轮（防止失控）。第 3 轮后我会主动给"建议收手"提示。

---

## 6. Phase C — 合成新 metadata（我直接在对话里完成）

### 输入
- Phase A 的 current_tokens 中**值得保留的词**（合成时过滤策略：rank ≤ 20 且 popularity ≥ 10；与 Phase A 全量保留不冲突 — Phase A 数据齐全，Phase C 合成时按场景筛）
- Phase B 用户接受的新候选词
- `ASO_methodology.txt` 中：
  - §5.3 主标题命名策略
  - §6.2 副标题原则（不要重复标题词、不要笼统）
  - §7.3 关键词字段 9 条最佳实践
  - §10.4 拆词组词（中文场景下逗号策略）
  - §2.4 复数 vs 复合词（视语言决定是否要变体）

### 输出（直接打在对话里 + 写一份 markdown）
```markdown
## 新元数据建议（GBrowser · CN · zh-Hans）

### 主标题（30 字符限制）
**Old**: `GBrowser:Choose Link Openly`（26 char）
**New**: `谷歌浏览器:多浏览器一键切换`（14 char + 1 = 15）
- 嵌入: 谷歌浏览器, 浏览器
- Rationale: 主市场是 CN，主标题用中文核心词权重最高

### 副标题（30 字符限制）
**Old**: `Any link in any browser浏览器下载`（24 char）
**New**: `chrome / firefox / edge 一键选择`（25 char）
- 嵌入: chrome, firefox, edge
- Rationale: 副标题不重复主标题词，把 3 个高 pop 浏览器品牌词放进来

### 关键词字段（100 字符限制）
**Old**: `谷歌浏览器,chrome,火狐edge安装firefox...`（99 char）
**New**: `chrome,firefox,edge,arc,hover,谷歌,谷歌地图,谷歌翻译,谷歌邮箱,360,qq,网址,链接,默认`（<计算后字符数>）
- 删除的旧词：MacOS, app, 系统, 火狐(已在标题), 安装(已在标题)
- 新加入：谷歌地图, 谷歌翻译, 谷歌邮箱, 网址, 链接
- Rationale:
  - 删 MacOS/app — §7.3 第7条免费词无需占位
  - 删 系统/安装 — Astro 显示 pop < 10 且 rank > 100
  - 新加入"谷歌系列" — Apple 已认为相关（rank 2-5），高 pop 30+
```

---

## 7. 文件输出

| 路径 | 内容 | 何时写 |
|---|---|---|
| `phase_a_<app_slug>.json` | Phase A 现状数据 | 每次跑 analyze 时覆盖 |
| `phase_b_<app_slug>.json` | Phase B 候选词验证结果 | 每次跑 validate 时覆盖 |
| `aso_optimize_<app_slug>.md` | 最终建议（Phase C） | Phase C 结束时写入 |

`<app_slug>` = app 名清洗后（如 `gbrowser_cn`）

---

## 8. CLI 接口完整定义

```bash
# Phase A
python3 aso_optimize.py analyze <app>

# Phase B Step 2 (validate)
python3 aso_optimize.py validate <app> --candidates kw1,kw2,kw3

# Optional helpers
python3 aso_optimize.py show-a <app>     # 打印 Phase A JSON 摘要
python3 aso_optimize.py show-b <app>     # 打印 Phase B JSON 摘要
```

无需 `phase=c` 子命令 — Phase C 全部在对话里由我完成。

---

## 9. 复用现有代码

直接 import 不重写：

| 来源 | 用什么 |
|---|---|
| `aso_optimize.py`（旧）| `find_top_market` / `pick_locales_for_country` / `tokenize_text` / 国家 storefront 映射 |
| `aso_report.py` | `is_download_ptid` / `rank_keyword` / `load_rank_cache` |
| `astro_client.py` | `lookup_popularity_batch` |
| `apps_full.json` | 静态 metadata |
| `sales_cache.json` | 销售数据（用于找主市场 + 算近 30 日下载） |

旧文件**保留**：`aso_daily.py` 继续做监控，本工具是补充。

---

## 10. ASO_methodology.txt 用法对照表

| Spec 章节 | 用到的方法论章节 |
|---|---|
| Phase B1 候选词生成 | §10.1 四象限/品牌词/行业词/竞品词，§10.4 拆词组词，§2.4 复数复合词 |
| Phase C 主标题合成 | §5.2 标题权重，§5.3 命名策略与品牌/关键词平衡 |
| Phase C 副标题合成 | §6.2 不重复标题词、避免笼统词 |
| Phase C 关键词字段合成 | §7.3 9 条最佳实践，§10.4 逗号策略 |

我会在每次 Phase B/C 工作前，**主动重新打开**这些章节确认细则。

---

## 11. 非目标 / Out of scope

- ❌ 不集成 AppMate RAG（竞品搜索）— 这一版只用现有数据 + 方法论，更可控
- ❌ 不集成 SoloMax RAG MCP — 同上
- ❌ 不写定时任务 — 全部按需触发
- ❌ 不做 A/B 测试方案 — 用户拿到建议后自行决定是否上线
- ❌ 不自动写回 App Store Connect — 仅输出文本字符串

后续如果发现 RAG 能补真正的盲点，再 spec v3 接入。

---

## 12. Testing approach

| 测试类型 | 怎么做 |
|---|---|
| 单元 | `tokenize_text` / `_good_token` 已在旧版用 — 不重测 |
| 集成 | 跑 `analyze sticky_note_pro` 看 JSON shape 是否合理 |
| 端到端 | 跑一遍 A→B→C 完整流程对 GBrowser（已知数据，能验证输出合理性） |
| LLM 输出质量 | 由我（Claude）+ 用户审核保证，没有自动断言 |

---

## 13. Open questions（建 backlog，不阻塞实现）

1. 多市场 app：当前固定取主市场。是否要支持"跑 top-2 市场各一份建议"？— 暂不做
2. 不同平台：当前只对 macOS / iOS 测试过。watchOS / tvOS 不在范围
3. 候选词生成的"种子方向"是否要让用户引导（"我想多挖品牌词" / "多挖长尾"）？— 暂不做，先看默认效果
