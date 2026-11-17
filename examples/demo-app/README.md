# Demo App

S3 交接演示的目标项目：Trae 需为 `index.html` 的密码输入框新增显示/隐藏切换。

使用约束：独立 git 仓库或 worktree 中运行；禁止在用户真实项目上执行演示任务。
测试命令与验收条件在 S3 阶段由 verifier 配置固化。
## 测试

```bash
node --test tests/password.test.mjs
```

S3 验收条件：仅允许修改 `index.html`；测试命令保持全绿；任何越界文件或测试失败均判 failed。
