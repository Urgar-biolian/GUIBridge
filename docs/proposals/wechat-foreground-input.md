# 提案：微信 send_message 增加 foreground_input 通道（待 B 评审 + owner approve）

**状态：PROPOSAL — 未应用。冻结能力表 `packages/routing/capabilities.draft.yaml`（status: frozen，R1 owner 2026-11-17 批准）未被本提案修改。**

冻结表条目改动属契约数据变更，须双人 approve（B 线评审 + owner 批准）。本文件给出拟议改动、实测证据与理由，供裁决；批准前 `wechat × send_message` 仍只有 `uia: {supported: false, risk: unknown}`，路由层不会放行任何微信写通道。

## 1. 拟议改动（批准后应用到冻结表）

`wechat × send_message` 条目（impact: high、idempotent: false 不变）的 channels 增加 `foreground_input`：

```yaml
  - app: wechat
    operation: send_message
    impact: high
    idempotent: false
    channels:
      uia: {supported: false, risk: unknown}
      foreground_input: {supported: true, risk: physical_input}   # 新增（实测）
    unsupported_reason: >
      wechat 4.x 聊天面 MMUIRenderSubWindowHW 完全自绘、UIA 零语义节点（E10），
      uia 不可用。可行写路径仅前台 OCR 定位 + 剪贴板粘贴 + 物理输入（E11），
      声明 physical_input；OCR 仅定位永不作写执行通道（原则 3）。
    evidence:
      - "run 20261119T113920Z E10: 渲染面 UIA node_count 0, has_edit/button false"
      - "run 20261119T120734Z E11: 前台发信 verified 气泡, success_with_interference, cursor 553"
      - "run 20261119T122840Z E11 复跑: title 防误发门控通过, 气泡读回 verified, cursor 553"
      - "run 20261119T122446Z E12: 隐藏桌面仅登录 QR 窗(368x484)非已登录聊天, 隐藏桌面发信不可行"
```

**无需改冻结 Channel 枚举**：`FOREGROUND_INPUT` 与 `InterferenceRisk.PHYSICAL_INPUT` 均已存在（native-test 条目已用）。本提案只往既有 wechat 条目加一个已枚举通道 + 实测风险定级。`send_message` 已在 `WRITE_OPERATIONS`（capability.py）与操作名 crosswalk 中，无新操作名。

## 2. 实测证据（实测优于假设）

| 实验 | run | 结论 |
| --- | --- | --- |
| E10 只读 | `20261119T113920Z` | 聊天渲染面 `MMUIRenderSubWindowHW` UIA **node_count=0**、has_edit/button/list 全 false ⇒ 完全自绘，**uia 后台语义读/写不可用**（supported: false, risk: unknown） |
| E10b 可见截图 | `20261119T114750Z` | 可见态 PrintWindow 非空白 + OCR 39 框 locate-only ⇒ **OCR 仅定位**成立（role=text/actions=[]），永不作写执行通道 |
| E11 前台发信 | `20261119T120734Z` / 复跑 `20261119T122840Z` | 前台 OCR+剪贴板真实发信到文件传输助手并 OCR 读回气泡 verified；四态 **success_with_interference**；cursor_displacement=**553**（移鼠标点发送=PHYSICAL_INPUT）、unexpected_focus_switch=false、event_hook_active=true；防误发标题门控 + 暂存复核通过 |
| E12 隐藏桌面 | `20261119T122446Z` | 隐藏桌面第二实例主机零干扰，但主窗是 **368×484 登录 QR 窗**非已登录聊天 ⇒ **隐藏桌面发信不可行**（卡登录层），不新增 hidden_desktop 微信通道 |

风险定级 `physical_input` 来自 E11 两次实测光标位移 553 + 前台物理输入，**非假设**。

## 3. 理由与原则对齐

- **原则 3（OCR 仅定位）**：foreground_input 是写执行通道；OCR 只用于导航定位与效果复核（防误发标题门控、暂存复核、气泡读回），不作写执行。
- **原则 7（高影响须审批）**：send_message impact=high，**即便 foreground_input 风险已知，仍须逐次用户审批**。适配器 `send_message(approve=False)` 默认拒绝（`approval_required`），在任何窗口动作之前 fail-stop，绝不自动审批。风险定级与审批正交。
- **原则 6（非幂等不自动重试）**：idempotent=false；适配器单次尝试，UNCONFIRMED 原样返回不重试。
- **四态诚实**：前台物理输入验证成功一律 `SUCCESS_WITH_INTERFERENCE`（classify 对 FOREGROUND_INPUT 通道直接定级），**不声称后台/无干扰**。
- **隐私**：OCR 派生证据仅保留目标系统标签 + 用户自建测试文本，其余聊天/联系人文本 `<redacted>`；可读 PNG 抓 repo 外即删；原始产物 gitignored 不入库。

## 4. 代码落点（已实现，单测通过，未接冻结引擎）

- `packages/adapters/wechat/adapter.py` — `WeChatAdapter.send_message(target, text, approve) -> ActionResult`（消息式，区别于任务式 TraeAdapter）；门控/审批/四态/脱敏/leave-as-found 清理。
- `packages/adapters/wechat/driver.py` — `WeChatDriver` 协议 + `Win32WeChatDriver`（可注入假驱动单测）。
- `packages/adapters/wechat/win32.py` — 自包含 Win32 原语 + 窗口白名单（仅 Qt51514QWindowIcon 主窗 + MMUIRenderSubWindowHW 渲染面）。
- `tests/test_wechat_adapter.py` — 12 例纯逻辑单测（假驱动，无真实微信/Win32/OCR）；全量基线 349 passed / 1 skipped。
- `probe_channels()` 返回 `{uia: False, ocr_vision: True, foreground_input: True}`（实测通道可用性）。

**未接冻结引擎/MCP/Dashboard**：与既有草案一致，正式接入与默认行为切换留 G1 集成门 + B 裁决。live 复跑须用户单独授权（`--upto send` 触发真实发送、发送前手动确认文本）。

## 5. 待裁决项

1. B 线评审 + owner approve 后，将 §1 的 `foreground_input` 通道写入冻结表 wechat 条目（双人 approve）。
2. 是否同时把 E12 的「隐藏桌面微信卡登录层」结论纳入 design 隔离阶梯脚注（无需新通道）。
3. 正式适配器接入冻结引擎的时机（G1 门、B 控制面合并后），不在本提案范围。