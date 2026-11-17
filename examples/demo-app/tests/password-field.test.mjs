// 演示仓库改动前后都必须通过：锁定密码框既有契约，S3 任务要求新按钮不破坏它。
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the password field stays bound to the app state", () => {
  assert.match(html, /<input[^>]*v-model="password"/);
  assert.match(html, /:type="showPassword\s\?\s['"]text['"]\s:\s['"]password['"]"/);
  assert.match(html, /showPassword:\s*false/);
});

test("the demo page keeps the labels the S5 script reads aloud", () => {
  assert.match(html, /<h1>登录示例<\/h1>/);
  assert.match(html, /<label>\s*密码/);
  assert.match(html, /mount\(["']#app["']\)/);
});
