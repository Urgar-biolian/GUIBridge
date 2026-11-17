// S3 演示任务的目标行为（见 index.html 的注释）。用例读静态 HTML 断言结构与状态绑定，
// 因为离线环境没有浏览器；真实点击行为留给 live 演示（docs/agent.md 的 S5 脚本）。
// 改动前本文件失败，verifier 判 failed；改动后两个文件都通过，verifier 才可能判 verified。
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const button = (html.match(/<button[^>]*data-testid="toggle-password"[^>]*>/) ?? [""])[0];

test("a toggle control exists next to the password field", () => {
  assert.ok(button, "no <button data-testid=\"toggle-password\">");
  assert.match(button, /id="toggle-password"/);
  assert.match(button, /type="button"/);
});

test("the control flips the same state the field is bound to", () => {
  assert.match(button, /@click="showPassword\s*=\s*!showPassword"/);
  assert.match(button, /:aria-pressed="showPassword"/);
});

test("the control labels the action it performs", () => {
  assert.match(button, /:aria-label="showPassword\s*\?\s*['"]隐藏密码['"]\s*:\s*['"]显示密码['"]"/);
  assert.match(html, /\{\{\s*showPassword\s*\?\s*['"]隐藏['"]\s*:\s*['"]显示['"]\s*\}\}/);
});
