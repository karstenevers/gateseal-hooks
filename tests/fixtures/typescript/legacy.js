export function jsTested(a) {
  return a ? "yes" : "no";
}

export function jsUntestedBranchy(a, b) {
  if (a > 10 && b) {
    return "big";
  }
  if (a < 0 || !b) {
    return "negative";
  }
  return "none";
}
