# FreeHire Job Monitor

面向 AI / Agent / LLM 岗位的本地求职看板：完整分页记录、规则筛选、重复职位合并、排除审计，以及持久化的“已投递 / 不合适”标记。

Python 3.9+，仅使用标准库。前端为原生 HTML/CSS/JavaScript，无需 npm 或数据库服务。项目独立于 FreeHire 官方产品。

## 快速运行

```sh
git clone https://github.com/JerryOctopus/freehire-job-monitor.git
cd freehire-job-monitor
python3 demo.py
python3 board.py serve
```

打开 http://127.0.0.1:8769/ 。若端口已占用，使用 `python3 board.py serve --port 8770`。

`demo.py` 创建纯虚构岗位的分页检查点并跑通筛选与审计。它会拒绝覆盖已有岗位或用户标记；只适合首次体验。直接运行 `board.py serve` 也可启动空看板。

## 功能与默认规则

- 搜索方案包含 7 路查询：中国大陆、港澳、新加坡、日本，以及全球/亚太远程补查。
- 近 14 天、最低经验要求不超过 5 年、排除 Intern / Internship / 实习 / インターン。
- 技能不是主查询硬门槛；读取 JD 后核对方向、经验及远程居住资格。不明条件保留为“待核实”。
- 按职位 ID、申请链接及同公司同地点相同 JD 去重；保留身份别名以延续历史决定。
- “已投递”“不合适”从待处理列表与活跃导出中隐藏；归档页可恢复。重启、更新不会清空标记。
- 看板支持搜索、筛选、分页及 JSON 下载；`/audit.html` 可查看候选和排除原因。

## 搜索和每日更新

仓库包含本地看板、编译程序和查询方案，**不内置 FreeHire 网络采集器、账号凭证或定时器**。真实搜索由你已授权的 FreeHire MCP / 外部采集流程执行。需要自行连接服务，并使用 `search-plan-v2.json` 执行查询；API 筛选字段以连接后的实际能力为准。

每轮在 `runs/<日期-时间>/` 写入分页 JSON 和 `manifest.json`。逐页保存，核对全部 offset、total 和错误后，执行：

```sh
python3 finalize_fullscan.py --scan-dir runs/<日期-时间>
python3 board.py export-active
```

每日任务可在自己的调度平台按 Asia/Shanghai 09:00 启动，目标 09:45 前完成。`monitor-policy.json` 是策略记录，本身不会安装调度任务。可参考 [每日任务说明](docs/daily-update.md)。

“完整”指本轮指定查询的分页完整，不表示全网无遗漏。发布来源持续变化，应保留检索起点和审计数据。

## 输入格式

每个分页文件名应形如 `core_local-0000.json`：

```json
{
  "id": "core_local",
  "args": {"offset": 0, "limit": 20},
  "total": 1,
  "offset": 0,
  "jobs": [{
    "public_slug": "example-ai-engineer",
    "title": "AI Engineer",
    "company": "Example Company",
    "location": "Shanghai, China",
    "description": "Requirements\nAt least 1 year of Python experience.",
    "posted_at": "2026-10-26T00:00:00Z",
    "url": "https://example.com/jobs/1",
    "enrichment": {"category": "ai_engineering"}
  }]
}
```

`manifest.json` 包含 `started_at`、`cutoff`（本轮起点减 14 天）和 `lanes`；每路包含 `id`、`total`、`rows_read`、`offsets`、`errors`。当前编译器按 20 条/页验证。运行 `demo.py` 可生成一套完整样例。

也可直接导入已经完成审核的清单：

```sh
python3 board.py publish path/to/results.json
python3 board.py export-active > active-jobs.json
python3 board.py export-all > all-jobs.json
```

输入为 `{"jobs": [...]}`。岗位可附带 `match` 对象，记录投递建议、优势、缺口、硬门槛和 JD–简历证据矩阵。本公开版本不含个人简历画像；默认只做规则初核，个人适配标为尚未分析。手工审核的 `match` 在同 slug 更新时保留。

## 数据保存与备份

| 文件 | 用途 |
| --- | --- |
| `board.py` | 本地 HTTP 服务、导入导出、SQLite 状态管理 |
| `compile_fullscan.py` | 职责/经验/地区/实习筛选与去重 |
| `finalize_fullscan.py` | 从分页检查点重建清单与审计 |
| `search-plan-v2.json` | 7 路查询方案 |
| `monitor-policy.json` | 每日更新策略 |
| `jobs.json` | 本地岗位及分析结果，运行时生成 |
| `decisions.sqlite3` | 用户决定，运行时生成 |
| `audit-index.json` | 所有检索记录的处理结果，运行时生成 |

备份时同时保存 `jobs.json` 和 `decisions.sqlite3`。不要重建或清空决策库；推送前重新读取 `export-active`。仓库忽略简历、个人画像、SQLite、抓取分页和生成的清单。发布代码前仍应检查 Git 暂存文件。

服务仅监听 `127.0.0.1`，用于单人本机使用，无远程鉴权；不要直接部署到公网。状态按钮只记录本地决定，不实际投递，也不修改 FreeHire 账号。

## 验证

```sh
python3 -B -m unittest discover -s tests -v
```

测试覆盖完整分页到审计的流程、实习排除，以及重新发布时已投递/不合适状态的保留。
