/** ISO 타임스탬프(예: "2026-07-29T14:05:17.900000+00:00")를 "YYYY-MM-DD HH:MM:SS.mmm"로
 * 표시한다. `Date` 객체를 거치지 않고 문자열을 직접 잘라서 만든다 — 브라우저
 * 로컬 타임존으로 변환하면(특히 VCS 서버의 로그에 찍힌, 타임존 정보 없이 그대로
 * 담긴 시각은) 실제 로그 파일의 시각과 화면에 보이는 값이 달라져 헷갈릴 수 있다.
 * `LogViewer`와 `CallEventDetailModal`이 공유한다. */
export function formatLogTimestamp(ts: string): string {
  const [datePart, rest] = ts.split("T");
  if (!rest) return ts;
  const withoutOffset = rest.replace(/(Z|[+-]\d{2}:\d{2})$/, "");
  const [hms, frac = ""] = withoutOffset.split(".");
  const time = frac ? `${hms}.${frac.slice(0, 3)}` : hms;
  return `${datePart} ${time}`;
}
