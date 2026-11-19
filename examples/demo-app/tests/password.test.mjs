import test from "node:test";
import assert from "node:assert/strict";

const { maskValue, initialState } = await import("../src/password.js").then(
  (m) => (m.default && m.default.maskValue ? m.default : m)
);

test("initial state hides the password", () => {
  assert.deepEqual(initialState(), { password: "", showPassword: false });
});

test("masked value never leaks characters", () => {
  assert.equal(maskValue("secret", false), "••••••");
  assert.equal(maskValue("secret", false).includes("s"), false);
});

test("visible value is returned verbatim", () => {
  assert.equal(maskValue("secret", true), "secret");
});
