export function testedSimple(a: number): number {
  return a + 1;
}

export function untestedBranchy(a: number, b: number[]): string {
  if (a > 10 && b.length > 0) {
    return "big";
  } else if (a < 0) {
    return "negative";
  }
  for (const n of b) {
    if (n === a) {
      return "found";
    }
  }
  return "none";
}

export function partlyTested(a: number): string {
  if (a > 100) {
    return "huge";
  }
  if (a > 10) {
    return "big";
  }
  return "small";
}

export function outerWithNested(items: number[]): number {
  function clamp(n: number): number {
    if (n > 10) {
      return 10;
    }
    if (n < 0) {
      return 0;
    }
    return n;
  }
  let total = 0;
  for (const n of items) {
    total += clamp(n);
  }
  return total;
}

export function outerWithUncalledCallback(items: number[]): number[] {
  if (items.length === 0) {
    return [];
  }
  return items.filter((n) => {
    if (n > 5 || n < -5) {
      return true;
    }
    return n === 0 ? true : false;
  });
}

export const identity = <T>(value: T) => value;

export const uncalledOneLiner = (x: number) => (x > 0 ? x * 2 : 0);

export const calledOneLiner = (x: number) => (x > 0 ? x * 2 : 0);

export class Account {
  private total = 0;

  deposit(amount: number): number {
    if (amount <= 0) {
      throw new Error("bad amount");
    }
    this.total += amount;
    return this.total;
  }

  withdraw(amount: number): number {
    if (amount <= 0) {
      throw new Error("bad amount");
    }
    if (amount > this.total) {
      throw new Error("too much");
    }
    while (amount > 0 && this.total > 0) {
      this.total -= 1;
      amount -= 1;
    }
    return this.total;
  }

  render = (prefix: string): string => {
    if (prefix.length > 3) {
      return prefix.slice(0, 3) + this.total;
    }
    return prefix ? prefix + this.total : String(this.total);
  };
}

export const handlers = {
  onSave(value: string | null): string {
    if (value === null) {
      return "empty";
    }
    try {
      return JSON.parse(value) ? "truthy" : "falsy";
    } catch {
      return "invalid";
    }
  },
  onLoad: (value: number): number => {
    switch (value) {
      case 1:
        return 10;
      case 2:
        return 20;
      default:
        return 0;
    }
  },
};

const wrap = <F extends (...args: never[]) => unknown>(fn: F): F => fn;

export const wrapped = wrap((n: number): string => {
  if (n > 2) {
    return "many";
  }
  if (n === 2) {
    return "two";
  }
  return n === 1 ? "one" : "none";
});

export default function (flag: boolean, other?: { deep?: { value?: number } }): number {
  if (flag) {
    return other?.deep?.value ?? 1;
  }
  return 0;
}
