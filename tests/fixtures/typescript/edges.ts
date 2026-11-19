export type * from "./cases";
export { default as data } from "./data.json" with { type: "json" };

export const paren = (x: number) => (x > 0 ? 1 : 2);
export const cast = (x: number) => (x > 0 ? 1 : 2) as number;
export const angle = (x: number) => <number>(x > 0 ? 1 : 2);
export const checked = (x: number) => (x > 0 ? 1 : 2) satisfies number;
export const sure = (x: number | null) => (x ? x : null)!;

export const factory = () => function handler(x: number): number {
  if (x > 3) return 4;
  return 1;
};

export const made = () => <() => number>(function inner() { return 1; });

export function later(): (x: number) => Promise<number> {
  const wait = async (x: number) => { if (x > 0) return 1; return 2; };
  return wait;
}

export function choose(flag: boolean) {
  const pick = flag ? function one() { return 1; } : function two() { return 2; };
  const either = function left() { return 3; } || function right() { return 4; };
  return [pick, either];
}

export const curried = (a: number) => (b: number) => (a > b ? a : b);
export const thunk = () => () => 1;
export const hollow = () => () => {};

const pass = <F>(fn: F): F => fn;

export function named(cb = function inner() { return 1; }) { return cb(); }
export function held(cb = () => 1) { return cb; }
export function passed(cb = pass(() => 1)) { return cb; }

export function unpack(options: { handle?: (x: number) => number; use?: () => number }) {
  const { handle = (x: number) => (x > 0 ? x : 0) } = options;
  const { use: renamed = () => 1 } = options;
  const [first = (x: number) => (x ? 1 : 0)] = [];
  return [handle, renamed, first];
}

export function keyed(a: boolean, b: boolean) {
  return { [a && b ? "on" : "off"](): number { return 1; } };
}

export function tagged() {
  return { [(() => "k")()]() {} };
}

export class Box {
  handler = (x: number): number => {
    if (x > 0) return 1;
    return 2;
  };
}

export function dispose(items: Disposable[]): number {
  let count = 0;
  for (using item of items) {
    if (item) count += 1;
  }
  return count;
}

export function idle(): number {
  function nested() { return 1; }
  return nested();
}

export function packed(items: number[]): number { items.map(n => n + 1); const inner = () => 1; return inner(); }

export function noop(): void {}
export enum Mode { On, Off }
export function unused(): void {}

export const wide = "😀😀😀😀😀😀😀😀😀😀"; export const after = (x: number) => x;

export const split =
  () => (x: number) => (x ? 1 : x ? 2 : 3);
