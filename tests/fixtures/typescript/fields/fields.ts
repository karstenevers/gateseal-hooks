export class Panel {
  idle = (x: number) => (x ? 1 : x ? 2 : 3);
  used = (x: number) => (x ? 1 : x ? 2 : 3);
  empty = () => 0;
  mapper = (xs: number[]) => xs.map(i => i + 1);
  curry = (x: number) => () => x;
}
