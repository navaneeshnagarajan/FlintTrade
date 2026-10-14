// Deliberate attack control. Only loaded by the separately labelled negative test.
// Constant payload only: no interpolation, external input or production import.
try {
  new Function("globalThis.__r33EvalExecuted = true")();
  globalThis.__r33EvalNegative = "executed";
} catch (error) {
  globalThis.__r33EvalNegative = error.name;
}
