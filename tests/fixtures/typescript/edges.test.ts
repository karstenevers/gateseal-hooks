import { test } from "vitest";
import assert from "node:assert";
import {
  paren,
  angle,
  sure,
  factory,
  made,
  later,
  choose,
  curried,
  thunk,
  hollow,
  named,
  held,
  passed,
  unpack,
  keyed,
  tagged,
  Box,
  dispose,
  packed,
  noop,
  after,
  split,
  shell,
} from "./edges.ts";

test("edges", async () => {
  assert.equal(paren(1), 1);
  assert.equal(angle(1), 1);
  assert.equal(sure(1), 1);
  assert.equal(factory()(1), 1);
  assert.equal(typeof made(), "function");
  assert.equal(await later()(1), 1);
  const [pick, either] = choose(true);
  assert.equal(pick(), 1);
  assert.equal(either(), 3);
  assert.equal(typeof curried(1), "function");
  assert.equal(typeof thunk(), "function");
  hollow()();
  assert.equal(named(), 1);
  assert.equal(typeof held(), "function");
  assert.equal(passed(() => 2)(), 2);
  const [handle] = unpack({});
  assert.equal(handle(1), 1);
  assert.equal(typeof keyed(true, false), "object");
  assert.equal(typeof tagged(), "object");
  assert.equal(new Box().handler(0), 2);
  assert.equal(dispose([]), 0);
  assert.equal(packed([]), 1);
  noop();
  assert.equal(after(1), 1);
  assert.equal(typeof split(), "function");
  assert.equal(typeof shell(), "function");
});
