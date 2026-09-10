import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalOutcomeAssignment, PortalOutcomeSchema, PortalOutcomeSubmitResult } from "../../api/types";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

interface PortalOutcomePageProps {
  assignmentId: string;
  onDone: () => void;
}

export function PortalOutcomePage({ assignmentId, onDone }: PortalOutcomePageProps) {
  const [assignment, setAssignment] = useState<PortalOutcomeAssignment | null>(null);
  const [schema, setSchema] = useState<PortalOutcomeSchema | null>(null);
  const [responses, setResponses] = useState<Record<string, unknown>>({});
  const [activities, setActivities] = useState<Array<{ name: string; rating: number | "" }>>([{ name: "", rating: "" }]);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PortalOutcomeSubmitResult | null>(null);

  useEffect(() => {
    let active = true;
    api
      .portalOutcomeDetail(assignmentId)
      .then((result) => {
        if (!active) return;
        setAssignment(result.assignment);
        setSchema(result.schema);
      })
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load this outcome measure.")));
    return () => {
      active = false;
    };
  }, [assignmentId]);

  async function submit() {
    setError("");
    setFieldErrors({});
    setSubmitting(true);
    try {
      let itemResponses: Record<string, unknown> = responses;
      if (schema?.kind === "activities") {
        itemResponses = {
          activities: activities
            .filter((activity) => activity.name.trim())
            .map((activity) => ({ name: activity.name.trim(), rating: Number(activity.rating) })),
        };
      }
      const submitResult = await api.portalOutcomeSubmit(assignmentId, itemResponses);
      setResult(submitResult);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 422) {
        setFieldErrors((requestError.fields as Record<string, string>) || {});
        setError("Please complete every item before submitting.");
      } else {
        setError(requestMessage(requestError, "Unable to submit this outcome measure."));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !schema) return <p className="form-error" role="alert">{error}</p>;
  if (!assignment || !schema) return <p className="portal-empty">Loading...</p>;

  if (result) {
    return (
      <div className="portal-card">
        <p className="eyebrow">{assignment.measureLabel}</p>
        <h2>Submitted</h2>
        <p>Your score: {result.score} / {result.maximumScore}</p>
        <p className="portal-empty">Your care team can see this result and how it changes over time.</p>
        <button className="secondary-button" onClick={onDone}>Back to outcome measures</button>
      </div>
    );
  }

  return (
    <>
      <h1>{assignment.measureLabel}</h1>
      <p className="portal-empty">{schema.instructions}</p>
      <section className="booking-card">
        {schema.kind === "items" && (
          <div style={{ display: "grid", gap: "1rem" }}>
            {schema.items?.map((item) => (
              <div key={item.key}>
                <p style={{ fontWeight: 600, margin: "0 0 .4rem" }}>{item.label}</p>
                <div style={{ display: "grid", gap: ".3rem" }}>
                  {item.choices.map((choice) => (
                    <label key={choice.value} style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
                      <input
                        type="radio"
                        name={item.key}
                        checked={responses[item.key] === choice.value}
                        onChange={() => setResponses((current) => ({ ...current, [item.key]: choice.value }))}
                        style={{ width: "auto" }}
                      />
                      {choice.label}
                    </label>
                  ))}
                </div>
                {fieldErrors[item.key] && <small className="form-error" role="alert">{fieldErrors[item.key]}</small>}
              </div>
            ))}
          </div>
        )}

        {schema.kind === "sections" && (
          <div style={{ display: "grid", gap: "1rem" }}>
            {schema.sections?.map((section) => (
              <div key={section.key}>
                <p style={{ fontWeight: 600, margin: "0 0 .4rem" }}>{section.label}</p>
                <div style={{ display: "grid", gap: ".3rem" }}>
                  {section.choices.map((choiceText, index) => (
                    <label key={index} style={{ display: "flex", alignItems: "flex-start", gap: ".5rem" }}>
                      <input
                        type="radio"
                        name={section.key}
                        checked={responses[section.key] === index}
                        onChange={() => setResponses((current) => ({ ...current, [section.key]: index }))}
                        style={{ width: "auto", marginTop: ".2rem" }}
                      />
                      {choiceText}
                    </label>
                  ))}
                </div>
                {fieldErrors[section.key] && <small className="form-error" role="alert">{fieldErrors[section.key]}</small>}
              </div>
            ))}
          </div>
        )}

        {schema.kind === "activities" && (
          <div style={{ display: "grid", gap: ".75rem" }}>
            {activities.map((activity, index) => (
              <div key={index} style={{ display: "grid", gap: ".4rem" }}>
                <label>
                  <span>Activity {index + 1}</span>
                  <input
                    value={activity.name}
                    onChange={(event) => {
                      const next = [...activities];
                      next[index] = { ...next[index], name: event.target.value };
                      setActivities(next);
                    }}
                    placeholder="e.g. Climbing stairs"
                  />
                </label>
                <label>
                  <span>Current ability (0 = unable, 10 = normal)</span>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={activity.rating}
                    onChange={(event) => {
                      const next = [...activities];
                      next[index] = { ...next[index], rating: event.target.value === "" ? "" : Number(event.target.value) };
                      setActivities(next);
                    }}
                  />
                </label>
              </div>
            ))}
            <div className="button-row">
              {activities.length < 5 && (
                <button className="secondary-button" type="button" onClick={() => setActivities([...activities, { name: "", rating: "" }])}>
                  + Add another activity
                </button>
              )}
              {activities.length > 1 && (
                <button className="text-action" type="button" onClick={() => setActivities(activities.slice(0, -1))}>
                  Remove last
                </button>
              )}
            </div>
          </div>
        )}

        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="button-row" style={{ marginTop: "1rem" }}>
          <button className="secondary-button" onClick={onDone} disabled={submitting}>Cancel</button>
          <button className="primary-button" onClick={() => void submit()} disabled={submitting}>
            {submitting ? "Submitting..." : "Submit"}
          </button>
        </div>
      </section>
    </>
  );
}
