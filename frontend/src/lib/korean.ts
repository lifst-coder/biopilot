/**
 * Korean particles after experiment codes read as digits ("#018" → "공일팔").
 * Digits whose reading ends in a vowel: 2 이, 4 사, 5 오, 9 구 (no final consonant).
 */
const VOWEL_FINAL = "2459";

type Pair = "과/와" | "은/는" | "이/가" | "을/를";

/** `josa("#018", "과/와")` → "#018과"; `josa("#019", "은/는")` → "#019는". */
export function josa(code: string, pair: Pair): string {
  const [withFinal, withoutFinal] = pair.split("/") as [string, string];
  const last = code.trim().slice(-1);
  return `${code}${VOWEL_FINAL.includes(last) ? withoutFinal : withFinal}`;
}
