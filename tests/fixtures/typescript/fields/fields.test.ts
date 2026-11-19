import assert from "node:assert/strict";
import { test } from "vitest";
import { Panel } from "./fields.ts";

test("fields", () => {
  const panel = new Panel();
  assert.equal(panel.used(1), 1);
  assert.deepEqual(panel.mapper([1]), [2]);
  assert.equal(typeof panel.curry(1), "function");
});
