# 数据库设计（SQLite 事件存储）

DDL：[packages/events/schema.sql](../packages/events/schema.sql)（schema_version=1）。
实现阶段：S2（`packages/events/store.py`）。

## 设计原则

1. **证据不可变**：`events`、`snapshots`、`task_transitions` 只追加不更新；审计回放依赖此不变量。
2. **三态分离落库**：`tasks.state` 取 submitted/running/awaiting_approval/claimed_done/verified/failed/unknown；`verified` 只能由独立验证器写入迁移链。
3. **审批不落明文**：`approvals.token_hash` 存哈希；scope_json 限定窗口+语义 ID+动作；一次性（used）+ 过期时间。
4. **定位器版本化**：`locators` 主键含 app_version；自修复产生 `heal_patches`（pending→approved/rejected），人工审核后才写 locators。
5. **JSON 列**：geometry/elements/chain/payload 用 JSON 文本列，避免过早关系化；查询热点已建索引。
6. **保留期**：默认 30 天清理 events/snapshots 及截图文件（配置项）；tasks 与 transitions 保留供评测复盘。

## 表职责

| 表 | 职责 |
|----|------|
| windows | 窗口白名单与几何跟踪（多显示器/DPI 实证风险 F8） |
| snapshots | 动作前后快照：截图路径 + 融合元素 JSON |
| tasks / task_transitions | 任务与状态迁移链（含证据 ID） |
| approvals | 高影响动作审批 token |
| events | 全动作审计：MCP 调用、定位、执行、修复、审批 |
| locators / heal_patches | 语义定位注册表与漂移补丁审核流 |

## 迁移策略

单文件 DDL + schema_version；S2 起变更以 `schema_vN.sql` 增量文件追加，store 启动时按版本顺序应用；不引入 ORM 迁移框架（规模不需要）。

## 隐私

截图仅目标窗口；image_path 指向本地证据目录（gitignore）；库文件本身不入 Git 远端。