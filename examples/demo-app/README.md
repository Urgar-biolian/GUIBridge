# demo-app

用于演示和测试的独立小应用，不包含生产代码。

- `index.html`：一个登录页（Vue 3 CDN）。密码框的显示/隐藏切换按钮与 `tests/` 里的验收用例是 S3
  任务的**参考实现**，仓库里保留两者，是为了让离线的验收链路真的能跑出 `verified`。
- live 演示时**只删实现**（index.html 里的按钮），保留 `tests/password-toggle.test.mjs` 并提交：
  连用例一起删会让 `node --test` 空转通过，验收锚点就失效了。
  `tests/test_live_handoff.py` 先跑一次这条命令，确认剥离后的基线确实失败才继续。

## 验收命令

规划侧（verifier）跑的是这一条，不依赖 npm：

    node --test tests/*.test.mjs

模式由 node 自己展开，`--test tests` 这种目录写法在 node 24 下会被当成模块路径而报错。
verifier 以 argv 列表执行，不经 shell，因此 Windows 路径里的反斜杠不会被再次解释。

三条用例的分工：

| 文件 | 断言 | 未改动时 |
|---|---|---|
| `tests/password-field.test.mjs` | 密码框既有契约（绑定 `password`/`showPassword`、标题与标签） | 通过 |
| `tests/password-toggle.test.mjs` | 切换按钮的存在、`@click` 翻转同一状态、`aria-*` 与文案 | 失败 |
| `tests/password.test.mjs` | `src/password.js` 的掩码与初始状态（纯函数单测，不读 HTML） | 通过 |

「未改动时」指的是 live 演示删掉按钮之后的基线；仓库里带参考实现提交时三条全过。
用例读取静态 HTML 断言结构与绑定，因为离线环境没有浏览器；真实点击行为由 live 演示在浏览器里确认。
verifier 不看用例"看起来对不对"，只看这条命令的退出码与 Git 变更范围，
见 [docs/agent.md](../../docs/agent.md) 的信任边界。

`src/password.js` 是感知线补的纯逻辑模块，只被上面那条单测使用：`index.html` 没有引用它，因为
`password-field.test.mjs` 断言的是页面里的字面绑定 `showPassword: false`，把 `data()` 换成
`initialState()` 会让这条验收锚点在基线就变红。「仅允许修改 `index.html`」是感知线当时的验收条件，
合并后统一放宽为任务包里的 `allow_files=["index.html", "tests/"]`——补测试本来就是任务的一部分。

## 隔离要求

演示必须在独立 git 仓库副本里跑，禁止指向任何用户真实项目：

    python examples/handoff_demo.py --workspace C:/tmp/guibridge-demo

`prepare_workspace` 会把本目录复制成独立的本地仓库（无 remote）；带 remote 的目录一律拒绝。
`examples/demo-app` 自身的提交历史属于主仓库，不能作为验证基线。

## 已知限制

退出码分不清「测试通过」与「没有测试可跑」。如果执行侧删掉了验收用例，`node --test` 仍会返回 0，
verifier 能做的只是把这条事实摆进报告：`verification.changes.deleted` 里会出现
`tests/password-toggle.test.mjs`，`report["verification"]["evidence"]` 一并入事件存储，由规划侧据此否决。
