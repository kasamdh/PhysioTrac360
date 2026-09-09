import { useRef, useState, type MouseEvent } from "react";
import { Trash2 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

export interface PainMapPoint {
  id: string;
  view: "anterior" | "posterior";
  x: number;
  y: number;
  region: string;
  quality: string;
  severity: string;
  note: string;
}

export const PAIN_QUALITIES = ["Sharp", "Dull", "Aching", "Burning", "Throbbing", "Numbness", "Tingling", "Other"];

function newPointId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `point-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

interface BodySilhouetteProps {
  view: "anterior" | "posterior";
  label: string;
  points: PainMapPoint[];
  selectedId: string | null;
  disabled?: boolean;
  onAddPoint: (x: number, y: number) => void;
  onSelectPoint: (id: string) => void;
}

// Original, deliberately schematic humanoid outline (basic shapes only — no
// traced or copyrighted anatomical artwork) so the front/back diagrams work
// fully offline with no external image asset.
function BodySilhouette({ view, label, points, selectedId, disabled, onAddPoint, onSelectPoint }: BodySilhouetteProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  function handleSvgClick(event: MouseEvent<SVGSVGElement>) {
    if (disabled || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    onAddPoint(x, y);
  }

  const viewPoints = points.filter((point) => point.view === view);

  return (
    <div className="text-center">
      <p className="m-0 mb-1 text-xs font-bold uppercase tracking-wide text-muted-foreground">{label}</p>
      <svg
        ref={svgRef}
        viewBox="0 0 100 220"
        className={`mx-auto h-[280px] w-[130px] rounded-md border border-border bg-slate-50 ${disabled ? "" : "cursor-crosshair"}`}
        onClick={handleSvgClick}
        role="img"
        aria-label={`${label} body diagram${disabled ? "" : " — click to mark a pain location"}`}
      >
        <ellipse cx="50" cy="16" rx="13" ry="15" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        {view === "anterior" ? (
          <>
            <circle cx="45" cy="15" r="1.4" className="fill-slate-400" />
            <circle cx="55" cy="15" r="1.4" className="fill-slate-400" />
          </>
        ) : (
          <line x1="50" y1="6" x2="50" y2="26" className="stroke-slate-400" strokeWidth={1} />
        )}
        <rect x="45" y="30" width="10" height="7" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <path d="M32,37 Q50,33 68,37 L65,110 Q50,116 35,110 Z" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        {view === "posterior" && (
          <line x1="50" y1="40" x2="50" y2="108" className="stroke-slate-400" strokeWidth={0.75} strokeDasharray="2,2" />
        )}
        <path d="M32,40 L18,95 L23,98 L38,50 Z" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <path d="M68,40 L82,95 L77,98 L62,50 Z" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <circle cx="19" cy="99" r="4" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <circle cx="81" cy="99" r="4" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <path d="M36,110 L30,200 L40,200 L48,113 Z" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <path d="M64,110 L70,200 L60,200 L52,113 Z" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <ellipse cx="32" cy="205" rx="6" ry="4" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />
        <ellipse cx="68" cy="205" rx="6" ry="4" className="fill-slate-200 stroke-slate-400" strokeWidth={1} />

        {viewPoints.map((point) => (
          <circle
            key={point.id}
            cx={point.x * 100}
            cy={point.y * 220}
            r={point.id === selectedId ? 4.5 : 3.5}
            className={point.id === selectedId ? "fill-red-600 stroke-white" : "fill-red-500/80 stroke-white"}
            strokeWidth={1}
            style={{ cursor: disabled ? "default" : "pointer" }}
            onClick={(event) => {
              event.stopPropagation();
              onSelectPoint(point.id);
            }}
          />
        ))}
      </svg>
    </div>
  );
}

interface BodyChartProps {
  points: PainMapPoint[];
  onChange: (points: PainMapPoint[]) => void;
  disabled?: boolean;
}

export function BodyChart({ points, onChange, disabled }: BodyChartProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  function addPoint(view: "anterior" | "posterior", x: number, y: number) {
    const point: PainMapPoint = { id: newPointId(), view, x, y, region: "", quality: "Aching", severity: "", note: "" };
    onChange([...points, point]);
    setSelectedId(point.id);
  }

  function updatePoint(id: string, patch: Partial<PainMapPoint>) {
    onChange(points.map((point) => (point.id === id ? { ...point, ...patch } : point)));
  }

  function removePoint(id: string) {
    onChange(points.filter((point) => point.id !== id));
    setSelectedId((current) => (current === id ? null : current));
  }

  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">
        {disabled
          ? points.length
            ? "Marked pain locations."
            : "No pain locations were marked on this note."
          : "Click the diagram to mark a pain location, then describe it below."}
      </p>
      <div className="flex flex-wrap justify-center gap-8">
        <BodySilhouette
          view="anterior"
          label="Front"
          points={points}
          selectedId={selectedId}
          disabled={disabled}
          onAddPoint={(x, y) => addPoint("anterior", x, y)}
          onSelectPoint={setSelectedId}
        />
        <BodySilhouette
          view="posterior"
          label="Back"
          points={points}
          selectedId={selectedId}
          disabled={disabled}
          onAddPoint={(x, y) => addPoint("posterior", x, y)}
          onSelectPoint={setSelectedId}
        />
      </div>

      {points.length > 0 && (
        <div className="mt-4 grid gap-2">
          {points.map((point) => (
            <div
              key={point.id}
              className={`cursor-pointer rounded-md border p-3 ${point.id === selectedId ? "border-red-300 bg-red-50" : "border-border"}`}
              onClick={() => setSelectedId(point.id)}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {point.view === "anterior" ? "Front" : "Back"} location
                </span>
                {!disabled && (
                  <button
                    type="button"
                    aria-label="Remove pain location"
                    className="border-0 bg-transparent p-1 text-destructive"
                    onClick={(event) => {
                      event.stopPropagation();
                      removePoint(point.id);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Region</span>
                  <Input
                    value={point.region}
                    disabled={disabled}
                    placeholder="e.g. Right shoulder"
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => updatePoint(point.id, { region: event.target.value })}
                    className="h-9 text-sm"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Quality</span>
                  <Select
                    uiSize="sm"
                    value={point.quality}
                    disabled={disabled}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => updatePoint(point.id, { quality: event.target.value })}
                    className="h-9 w-full"
                  >
                    {PAIN_QUALITIES.map((quality) => (
                      <option key={quality} value={quality}>{quality}</option>
                    ))}
                  </Select>
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Severity (0-10)</span>
                  <Input
                    type="number"
                    min={0}
                    max={10}
                    value={point.severity}
                    disabled={disabled}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => updatePoint(point.id, { severity: event.target.value })}
                    className="h-9 text-sm"
                  />
                </label>
              </div>
              <label className="mt-2 block text-sm">
                <span className="mb-1 block font-semibold text-foreground">Note</span>
                <Input
                  value={point.note}
                  disabled={disabled}
                  placeholder="Optional detail"
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => updatePoint(point.id, { note: event.target.value })}
                  className="h-9 text-sm"
                />
              </label>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
