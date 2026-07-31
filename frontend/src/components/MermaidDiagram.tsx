/**
 * Mermaid sequenceDiagram 렌더러 래퍼.
 *
 * 별도 다이어그램 엔진을 새로 만들지 않고 `mermaid` 패키지를 사용한다
 * (CLAUDE.md §4/§9). 백엔드가 생성한 `mermaid_source` 텍스트를 그대로 그린다.
 *
 * `messages`/`onMessageClick`이 주어지면 클릭-투-로그 기능을 켠다: Mermaid는
 * sequenceDiagram 메시지(화살표) 자체에 대한 클릭 바인딩 문법을 지원하지
 * 않아서(참가자 박스만 가능), 렌더된 SVG에서 메시지 라벨/화살표 엘리먼트를
 * 문서 순서대로 찾아 `messages` 배열과 index로 매칭해서 직접 클릭 리스너를
 * 붙인다 — `securityLevel: "strict"`가 svg 자체에 심는 onclick/스크립트는
 * DOMPurify로 지워버리지만, innerHTML 대입 이후에 JS로 addEventListener하는
 * 건 영향받지 않는다.
 *
 * 텍스트 라벨(`.messageText`)에만 리스너를 달았더니 "클릭해도 반응이 없다"는
 * 피드백이 있었다. 두 가지를 실제 mermaid.js 소스 + headless 브라우저로
 * 검증해서 고쳤다:
 *   1. 화살표 선(`.messageLine0`/`.messageLine1`)은 굵기가 1~2px라 정확히
 *      클릭하기 어렵다 — 메시지 하나당 텍스트 1개 + 선 1개가 항상 이 순서로
 *      나란히 렌더되므로(mermaid.js 소스로 확인) 선에도 리스너를 달고,
 *      같은 좌표에 굵은(stroke-width 14) 히트 영역을 겹쳐 그려 클릭하기
 *      쉽게 만든다.
 *   2. SVG의 기본 `pointer-events: visiblePainted`는 요소가 실제로
 *      "칠해진"(불투명하게 보이는) 상태여야만 클릭을 받는다 — 히트 영역처럼
 *      투명한(`stroke: transparent`) 엘리먼트는 기본값으로는 클릭 자체가
 *      아예 등록되지 않는다(headless 테스트로 재현). 클릭 리스너를 다는
 *      모든 엘리먼트에 `pointer-events: all`을 명시해서 투명/칠 여부와
 *      무관하게 항상 클릭이 되도록 한다.
 */
import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";
import type { CallFlowMessage } from "../api/types";

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "default",
    // 성능 시험은 콜이 수십~수백 건 섞여서 "전체" 보기의 다이어그램 소스가
    // Mermaid 기본 한도(maxTextSize 50000자, maxEdges 500개)를 쉽게 넘어
    // "Maximum text size in diagram exceeded" 에러로 렌더링 자체가 실패했다
    // (2026-07-31 실 서버 리포트). 한도를 넉넉히 올린다 — ExecutionPage가
    // 콜이 2건 이상이면 기본으로 콜 1건만 선택해서 보여주므로(아래
    // call-flow-selected 기본값 참고) 이 큰 한도는 사용자가 명시적으로
    // "전체"를 선택했을 때만 실제로 쓰인다.
    maxTextSize: 900_000,
    maxEdges: 2000,
  });
  mermaidInitialized = true;
}

interface MermaidDiagramProps {
  source: string;
  messages?: CallFlowMessage[];
  onMessageClick?: (message: CallFlowMessage) => void;
}

export function MermaidDiagram({ source, messages, onMessageClick }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const renderId = useId().replace(/[:]/g, "-");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ensureMermaidInitialized();
    let cancelled = false;

    if (!source || !source.trim()) {
      setError(null);
      if (containerRef.current) containerRef.current.innerHTML = "";
      return;
    }

    mermaid
      .render(`mermaid-${renderId}`, source)
      .then(({ svg }) => {
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        setError(null);

        if (messages && messages.length > 0 && onMessageClick) {
          const textEls = containerRef.current.querySelectorAll<SVGTextElement>(".messageText");
          const lineEls = containerRef.current.querySelectorAll<SVGLineElement>(
            ".messageLine0, .messageLine1",
          );

          textEls.forEach((textEl, i) => {
            const message = messages[i];
            if (!message) return;
            const handleClick = () => onMessageClick(message);

            textEl.style.cursor = "pointer";
            textEl.style.pointerEvents = "all";
            textEl.addEventListener("click", handleClick);

            const lineEl = lineEls[i];
            if (lineEl) {
              lineEl.style.cursor = "pointer";
              lineEl.style.pointerEvents = "all";
              lineEl.addEventListener("click", handleClick);

              // 실제 화살표 선은 1~2px라 정밀 클릭이 어렵다 — 같은 좌표에
              // 투명하고 굵은 선을 겹쳐서 히트 영역만 넓힌다(시각적으로는
              // 안 보임). pointer-events:all이 없으면 투명한 엘리먼트는
              // 기본적으로 클릭을 아예 안 받는다(headless 테스트로 확인).
              const hitArea = lineEl.cloneNode(false) as SVGLineElement;
              hitArea.removeAttribute("class");
              hitArea.setAttribute("stroke", "transparent");
              hitArea.setAttribute("stroke-width", "14");
              hitArea.style.cursor = "pointer";
              hitArea.style.pointerEvents = "all";
              hitArea.addEventListener("click", handleClick);
              lineEl.insertAdjacentElement("afterend", hitArea);
            }
          });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Call Flow 렌더링 실패");
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, renderId, messages, onMessageClick]);

  if (error) {
    return (
      <div className="mermaid-error">
        Call Flow 렌더링 실패: {error}
        <pre>{source}</pre>
      </div>
    );
  }

  return <div className="mermaid-container" ref={containerRef} />;
}
