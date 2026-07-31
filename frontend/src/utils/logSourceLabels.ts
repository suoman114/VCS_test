/** 알려진 로그 소스의 한글 라벨. `LogViewer`(탭)와 `CallEventDetailModal`(메시지
 * 상세 팝업)이 같은 라벨을 써야 소스 표기가 화면마다 어긋나지 않는다. */
const KNOWN_SOURCE_LABELS: Record<string, string> = {
  vcsm_log: "VCSM (SIP)",
  vcmc_log: "VCMC (SIP+MCPTT)",
  vcmm_log: "VCMM (녹취 제어)",
  vctp_log: "vctp (패킷 릴레이)",
  sipp_log: "SIPp",
};

export function labelOfSource(source: string): string {
  return KNOWN_SOURCE_LABELS[source] ?? source;
}
