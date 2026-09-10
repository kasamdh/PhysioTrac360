import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalHepExercise, PortalHepProgram } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function videoEmbedUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.hostname.includes("youtube.com")) {
      const id = parsed.searchParams.get("v");
      return id ? `https://www.youtube.com/embed/${id}` : null;
    }
    if (parsed.hostname === "youtu.be") {
      return `https://www.youtube.com/embed/${parsed.pathname.slice(1)}`;
    }
    if (parsed.hostname.includes("vimeo.com")) {
      return `https://player.vimeo.com/video/${parsed.pathname.split("/").pop()}`;
    }
    return null;
  } catch {
    return null;
  }
}

function CompleteExerciseForm({ exercise, onLogged }: { exercise: PortalHepExercise; onLogged: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [painLevel, setPainLevel] = useState("");
  const [difficultyLevel, setDifficultyLevel] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    setError("");
    setSaving(true);
    try {
      await api.portalCompleteExercise(exercise.id, {
        painLevel: painLevel === "" ? null : Number(painLevel),
        difficultyLevel: difficultyLevel === "" ? null : Number(difficultyLevel),
        comment: comment.trim(),
      });
      setOpen(false);
      setPainLevel("");
      setDifficultyLevel("");
      setComment("");
      await onLogged();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to log this completion."));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return <button className="primary-button" onClick={() => setOpen(true)}>Mark completed</button>;
  }

  return (
    <div style={{ display: "grid", gap: ".5rem", marginTop: ".5rem" }}>
      <label>
        <span>Pain level (0 = none, 10 = worst)</span>
        <input type="number" min={0} max={10} value={painLevel} onChange={(event) => setPainLevel(event.target.value)} />
      </label>
      <label>
        <span>Difficulty (0 = easy, 10 = very hard)</span>
        <input type="number" min={0} max={10} value={difficultyLevel} onChange={(event) => setDifficultyLevel(event.target.value)} />
      </label>
      <label>
        <span>Comment (optional)</span>
        <input value={comment} onChange={(event) => setComment(event.target.value)} maxLength={500} />
      </label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="button-row">
        <button className="secondary-button" onClick={() => setOpen(false)} disabled={saving}>Cancel</button>
        <button className="primary-button" onClick={() => void submit()} disabled={saving}>
          {saving ? "Saving..." : "Log completion"}
        </button>
      </div>
    </div>
  );
}

function ExerciseCard({ exercise, onLogged }: { exercise: PortalHepExercise; onLogged: () => Promise<void> }) {
  const embedUrl = exercise.videoUrl ? videoEmbedUrl(exercise.videoUrl) : null;
  return (
    <div className="portal-appointment-card">
      <header>
        <div>
          <strong>{exercise.name}</strong>
          <div className="portal-empty">{exercise.dosage}</div>
        </div>
      </header>
      <p style={{ margin: 0 }}>{exercise.instructions}</p>
      {exercise.precautionNote && <p className="form-error" role="alert" style={{ margin: 0 }}>{exercise.precautionNote}</p>}
      {embedUrl && (
        <iframe
          src={embedUrl}
          title={`${exercise.name} video`}
          style={{ width: "100%", aspectRatio: "16/9", border: 0, borderRadius: "8px" }}
          allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      )}
      {!embedUrl && exercise.videoUrl && (
        <a href={exercise.videoUrl} target="_blank" rel="noreferrer" className="secondary-button" style={{ width: "fit-content" }}>
          Watch video
        </a>
      )}
      <p className="portal-empty">
        {exercise.lastCompletedAt ? `Last completed ${formatDate(exercise.lastCompletedAt)}.` : "Not completed yet."}
      </p>
      <CompleteExerciseForm exercise={exercise} onLogged={onLogged} />
    </div>
  );
}

export function PortalHepPage() {
  const [program, setProgram] = useState<PortalHepProgram | null | undefined>(undefined);
  const [error, setError] = useState("");

  async function load() {
    try {
      setProgram((await api.portalHep()).program);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your home exercise program."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (program === undefined) return <p className="portal-empty">Loading...</p>;

  return (
    <>
      <h1>Home Exercise Program</h1>
      {!program ? (
        <p className="portal-empty">No active home exercise program right now.</p>
      ) : (
        <>
          <div className="portal-card">
            <p className="eyebrow">{program.title}</p>
            <p style={{ margin: 0 }}>{program.patientInstructions}</p>
            {program.precautions && <p className="form-error" role="alert">{program.precautions}</p>}
            <p className="portal-empty">{program.completionsLast7Days} completion{program.completionsLast7Days === 1 ? "" : "s"} in the last 7 days.</p>
          </div>
          <div style={{ display: "grid", gap: ".75rem" }}>
            {program.exercises.map((exercise) => (
              <ExerciseCard key={exercise.id} exercise={exercise} onLogged={load} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
