/**
 * Mermaid sequenceDiagram 렌더러 래퍼.
 *
 * 별도 다이어그램 엔진을 새로 만들지 않고 `mermaid` 패키지를 사용한다
 * (CLAUDE.md §4/§9). 백엔드가 생성한 `mermaid_source` 텍스트를 그대로 그린다.
 *
 * `messages`/`onMessageClick`이 주어지면 클릭-투-로그 기능을 켠다: Mermaid는
 * sequenceDiagram 메시지(화살표) 자체에 대한 클릭 바인딩 문법을 지원하지
 * 않아서(참가자 박스만 가능), 렌더된 SVG에서 메시지 라벨 엘리먼트
 * (`.messageText`, Mermaid가 항상 이 클래스로 렌더하며 Note는 `.noteText`라
 * 섞이지 않는다)를 문서 순서대로 찾아 `messages` 배열과 index로 매칭해서
 * 직접 클릭 리스너를 붙인다 — `securityLevel: "strict"`가 svg 자체에 심는
 * onclick/스크립트는 DOMPurify로 지워버리지만, innerHTML 대입 이후에 JS로
 * addEventListener하는 건 영향받지 않는다.
 */
import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";
import type { CallFlowMessage } from "../api/types";

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) return;
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "default" });
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
          const messageEls = containerRef.current.querySelectorAll<SVGTextElement>(".messageText");
          messageEls.forEach((el, i) => {
            const message = messages[i];
            if (!message) return;
            el.style.cursor = "pointer";
            el.addEventListener("click", () => onMessageClick(message));
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
