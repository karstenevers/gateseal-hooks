import { test } from "vitest";
import assert from "node:assert";
import {
  testedSimple,
  partlyTested,
  outerWithNested,
  outerWithUncalledCallback,
  identity,
  calledOneLiner,
  Account,
} from "./cases.ts";
import { jsTested } from "./legacy.js";

test("cases", () => {
  assert.equal(testedSimple(1), 2);
  assert.equal(partlyTested(5), "small");
  assert.equal(outerWithNested([5]), 5);
  assert.deepEqual(outerWithUncalledCallback([]), []);
  assert.equal(identity(3), 3);
  assert.equal(calledOneLiner(2), 4);
  assert.equal(new Account().deposit(5), 5);
  assert.equal(jsTested(true), "yes");
});
