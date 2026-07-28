/**
 * Mermaid sequenceDiagram 렌더러 래퍼.
 *
 * 별도 다이어그램 엔진을 새로 만들지 않고 `mermaid` 패키지를 사용한다
 * (CLAUDE.md §4/§9). 백엔드가 생성한 `mermaid_source` 텍스트를 그대로 그린다.
 */
import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) return;
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "default" });
  mermaidInitialized = true;
}

interface MermaidDiagramProps {
  source: string;
}

export function MermaidDiagram({ source }: MermaidDiagramProps) {
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
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
          setError(null);
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
  }, [source, renderId]);

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
