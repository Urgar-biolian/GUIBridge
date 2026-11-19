// Shared password-field logic (zero dependencies, usable from browser and node:test).
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PasswordLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function maskValue(value, visible) {
    if (visible) return value;
    return "•".repeat(value.length);
  }

  function initialState() {
    return { password: "", showPassword: false };
  }

  return { maskValue, initialState };
});
