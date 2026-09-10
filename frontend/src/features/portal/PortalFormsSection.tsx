import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalFormOverview } from "../../api/types";
import { PortalFormPage } from "./PortalFormPage";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

const STATUS_LABEL: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
  expired: "Expired — please redo",
};

function FormsList({ onOpen }: { onOpen: (slug: string) => void }) {
  const [forms, setForms] = useState<PortalFormOverview[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .portalForms()
      .then((result) => active && setForms(result.forms))
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load your forms.")));
    return () => {
      active = false;
    };
  }, []);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!forms) return <p className="portal-empty">Loading your forms...</p>;

  return (
    <>
      <h1>Forms</h1>
      <div style={{ display: "grid", gap: ".75rem" }}>
        {forms.map((form) => (
          <div key={form.templateSlug} className="portal-appointment-card">
            <header>
              <div>
                <strong>{form.name}</strong>
                <div className="portal-empty">{STATUS_LABEL[form.status] || form.status}</div>
              </div>
              <span className={`status-pill ${form.status}`}>{STATUS_LABEL[form.status] || form.status}</span>
            </header>
            <div className="button-row">
              <button className="primary-button" onClick={() => onOpen(form.templateSlug)}>
                {form.status === "completed" ? "Review" : form.status === "in_progress" ? "Continue" : "Start"}
              </button>
            </div>
          </div>
        ))}
        {forms.length === 0 && <p className="portal-empty">No forms are assigned right now.</p>}
      </div>
    </>
  );
}

export function PortalFormsSection() {
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  if (activeSlug) {
    return <PortalFormPage templateSlug={activeSlug} onDone={() => setActiveSlug(null)} />;
  }
  return <FormsList onOpen={setActiveSlug} />;
}
