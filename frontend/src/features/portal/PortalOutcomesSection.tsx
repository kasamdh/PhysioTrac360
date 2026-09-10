import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalOutcomeAssignment } from "../../api/types";
import { formatDate } from "../../lib/format";
import { PortalOutcomePage } from "./PortalOutcomePage";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function OutcomesList({ onOpen }: { onOpen: (id: string) => void }) {
  const [assignments, setAssignments] = useState<PortalOutcomeAssignment[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .portalOutcomes()
      .then((result) => active && setAssignments(result.assignments))
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load your outcome measures.")));
    return () => {
      active = false;
    };
  }, []);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!assignments) return <p className="portal-empty">Loading...</p>;

  const pending = assignments.filter((assignment) => assignment.status === "pending");
  const completed = assignments.filter((assignment) => assignment.status === "completed");

  return (
    <>
      <h1>Outcome Measures</h1>
      <p className="portal-empty">Your care team uses these to track your progress over time.</p>

      <div>
        <p className="portal-section-heading">To complete</p>
        {pending.length ? (
          <div style={{ display: "grid", gap: ".6rem", marginTop: ".6rem" }}>
            {pending.map((assignment) => (
              <div key={assignment.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>{assignment.measureLabel}</strong>
                    <div className="portal-empty">Assigned {formatDate(assignment.assignedAt)}</div>
                  </div>
                </header>
                <div className="button-row">
                  <button className="primary-button" onClick={() => onOpen(assignment.id)}>Start</button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="portal-empty">Nothing due right now.</p>
        )}
      </div>

      {completed.length > 0 && (
        <div>
          <p className="portal-section-heading">Completed</p>
          <ul className="record-list" style={{ marginTop: ".6rem" }}>
            {completed.map((assignment) => (
              <li key={assignment.id}>
                <span><strong>{assignment.measureLabel}</strong></span>
                <span className="status-pill completed">Completed</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

export function PortalOutcomesSection() {
  const [activeId, setActiveId] = useState<string | null>(null);

  if (activeId) {
    return <PortalOutcomePage assignmentId={activeId} onDone={() => setActiveId(null)} />;
  }
  return <OutcomesList onOpen={setActiveId} />;
}
