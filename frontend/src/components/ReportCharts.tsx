/**
 * 리포트 전용 차트 2종 — 콜 설정 시간 히스토그램 / 시간별 동시 통화 수 그래프
 * (2026-07-30 추가, CLAUDE.md §13 TBD 해소).
 *
 * 별도 차트 라이브러리를 새로 추가하지 않고 순수 SVG로 직접 그린다(CLAUDE.md
 * §4 "차트/그래프는 필요 최소한으로" 원칙, 리포트가 오프라인/인쇄 환경에서도
 * 깨지지 않아야 하므로 외부 스크립트 의존도 피한다).
 */
import "./ReportCharts.css";
import type { ConcurrencyPoint, HistogramBin } from "../api/types";

const CHART_WIDTH = 560;
const CHART_HEIGHT = 180;
const PADDING_LEFT = 44;
const PADDING_BOTTOM = 24;
const PADDING_TOP = 12;
const PADDING_RIGHT = 12;

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export function SetupTimeHistogramChart({ histogram }: { histogram: HistogramBin[] }) {
  const maxCount = Math.max(1, ...histogram.map((b) => b.count));
  const plotWidth = CHART_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const plotHeight = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const barGap = 4;
  const barWidth = histogram.length > 0 ? (plotWidth - barGap * (histogram.length - 1)) / histogram.length : 0;

  return (
    <svg
      className="report-chart"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label="콜 설정 시간 분포 히스토그램"
    >
      {/* y축 */}
      <line
        x1={PADDING_LEFT}
        y1={PADDING_TOP}
        x2={PADDING_LEFT}
        y2={CHART_HEIGHT - PADDING_BOTTOM}
        className="report-chart-axis"
      />
      {/* x축 */}
      <line
        x1={PADDING_LEFT}
        y1={CHART_HEIGHT - PADDING_BOTTOM}
        x2={CHART_WIDTH - PADDING_RIGHT}
        y2={CHART_HEIGHT - PADDING_BOTTOM}
        className="report-chart-axis"
      />
      <text x={4} y={PADDING_TOP + 6} className="report-chart-axis-label">
        {maxCount}건
      </text>
      <text x={4} y={CHART_HEIGHT - PADDING_BOTTOM} className="report-chart-axis-label">
        0
      </text>
      {histogram.map((bin, i) => {
        const barHeight = (bin.count / maxCount) * plotHeight;
        const x = PADDING_LEFT + i * (barWidth + barGap);
        const y = CHART_HEIGHT - PADDING_BOTTOM - barHeight;
        return (
          <g key={i}>
            <rect x={x} y={y} width={barWidth} height={barHeight} className="report-chart-bar">
              <title>
                {formatMs(bin.range_start_ms)} ~ {formatMs(bin.range_end_ms)}: {bin.count}건
              </title>
            </rect>
            {(i === 0 || i === histogram.length - 1) && (
              <text x={x} y={CHART_HEIGHT - PADDING_BOTTOM + 14} className="report-chart-axis-label">
                {formatMs(i === 0 ? bin.range_start_ms : bin.range_end_ms)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function ConcurrencyChart({ series }: { series: ConcurrencyPoint[] }) {
  const plotWidth = CHART_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const plotHeight = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const maxOffset = Math.max(1, ...series.map((p) => p.offset_sec));
  const maxConcurrent = Math.max(1, ...series.map((p) => p.concurrent_calls));

  const toX = (offsetSec: number) => PADDING_LEFT + (offsetSec / maxOffset) * plotWidth;
  const toY = (count: number) => CHART_HEIGHT - PADDING_BOTTOM - (count / maxConcurrent) * plotHeight;

  const linePoints = series.map((p) => `${toX(p.offset_sec)},${toY(p.concurrent_calls)}`).join(" ");
  const areaPoints =
    series.length > 0
      ? `${toX(series[0].offset_sec)},${CHART_HEIGHT - PADDING_BOTTOM} ${linePoints} ${toX(
          series[series.length - 1].offset_sec,
        )},${CHART_HEIGHT - PADDING_BOTTOM}`
      : "";

  return (
    <svg
      className="report-chart"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label="시간별 동시 통화 수 그래프"
    >
      <line
        x1={PADDING_LEFT}
        y1={PADDING_TOP}
        x2={PADDING_LEFT}
        y2={CHART_HEIGHT - PADDING_BOTTOM}
        className="report-chart-axis"
      />
      <line
        x1={PADDING_LEFT}
        y1={CHART_HEIGHT - PADDING_BOTTOM}
        x2={CHART_WIDTH - PADDING_RIGHT}
        y2={CHART_HEIGHT - PADDING_BOTTOM}
        className="report-chart-axis"
      />
      <text x={4} y={PADDING_TOP + 6} className="report-chart-axis-label">
        {maxConcurrent}콜
      </text>
      <text x={4} y={CHART_HEIGHT - PADDING_BOTTOM} className="report-chart-axis-label">
        0
      </text>
      <text x={PADDING_LEFT} y={CHART_HEIGHT - 2} className="report-chart-axis-label">
        0s
      </text>
      <text x={CHART_WIDTH - PADDING_RIGHT - 24} y={CHART_HEIGHT - 2} className="report-chart-axis-label">
        {maxOffset}s
      </text>
      {areaPoints && <polygon points={areaPoints} className="report-chart-area" />}
      {linePoints && <polyline points={linePoints} className="report-chart-line" />}
    </svg>
  );
}
