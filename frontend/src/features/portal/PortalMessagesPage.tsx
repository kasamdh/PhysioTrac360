import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalMessage } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

const CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "general", label: "General" },
  { value: "appointment", label: "Appointment" },
  { value: "hep", label: "Home exercise program" },
  { value: "billing", label: "Billing" },
  { value: "clinical", label: "Clinical" },
];

export function PortalMessagesPage() {
  const [messages, setMessages] = useState<PortalMessage[] | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("general");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [composeOpen, setComposeOpen] = useState(false);

  async function load() {
    try {
      setMessages((await api.portalMessages()).messages);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your messages."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSending(true);
    try {
      await api.portalSendMessage({ category, subject: subject.trim(), body: body.trim() });
      setSubject("");
      setBody("");
      setComposeOpen(false);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to send this message."));
    } finally {
      setSending(false);
    }
  }

  async function markRead(message: PortalMessage) {
    if (message.readAt || message.direction !== "inbound") return;
    try {
      await api.portalMarkMessageRead(message.id);
      await load();
    } catch {
      // best-effort — the message list still shows correctly either way
    }
  }

  return (
    <>
      <h1>Messages</h1>

      <div className="portal-card">
        <div className="button-row">
          <button className="primary-button" onClick={() => setComposeOpen((value) => !value)}>
            {composeOpen ? "Cancel" : "New message"}
          </button>
        </div>
        {composeOpen && (
          <form onSubmit={send} style={{ display: "grid", gap: ".6rem", marginTop: ".75rem" }}>
            <label>
              <span>What's this about?</span>
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Subject</span>
              <input value={subject} onChange={(event) => setSubject(event.target.value)} required maxLength={180} />
            </label>
            <label>
              <span>Message</span>
              <textarea rows={4} value={body} onChange={(event) => setBody(event.target.value)} required />
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="button-row">
              <button className="primary-button" type="submit" disabled={sending}>{sending ? "Sending..." : "Send"}</button>
            </div>
          </form>
        )}
      </div>

      {error && !composeOpen && <p className="form-error" role="alert">{error}</p>}

      <div style={{ display: "grid", gap: ".6rem" }}>
        {messages === null ? (
          <p className="portal-empty">Loading...</p>
        ) : messages.length ? (
          messages.map((message) => (
            <div key={message.id} className="portal-appointment-card" onClick={() => void markRead(message)}>
              <header>
                <div>
                  <strong>{message.subject}</strong>
                  <div className="portal-empty">
                    {message.direction === "outbound" ? "You" : message.counterpartName} · {message.categoryLabel} · {formatDate(message.createdAt)}
                  </div>
                </div>
                {message.direction === "inbound" && !message.readAt && <span className="status-pill scheduled">New</span>}
              </header>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{message.body}</p>
            </div>
          ))
        ) : (
          <p className="portal-empty">No messages yet.</p>
        )}
      </div>
    </>
  );
}
