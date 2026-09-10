import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalDocument } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function PortalDocumentsPage() {
  const [documents, setDocuments] = useState<PortalDocument[] | null>(null);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [uploading, setUploading] = useState(false);

  async function load() {
    try {
      setDocuments((await api.portalDocuments()).documents);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your documents."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setError("");
    setUploading(true);
    try {
      await api.portalUploadDocument(file, title.trim() || file.name, description.trim());
      setFile(null);
      setTitle("");
      setDescription("");
      (event.target as HTMLFormElement).reset();
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to upload this document."));
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      <h1>Documents</h1>

      <div className="portal-card">
        <h3>Upload a document</h3>
        <p className="portal-empty">Share outside records (e.g. imaging reports) with your care team.</p>
        <form onSubmit={upload} style={{ display: "grid", gap: ".6rem" }}>
          <label>
            <span>File</span>
            <input
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.doc,.docx"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              required
            />
          </label>
          <label>
            <span>Title (optional)</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            <span>Description (optional)</span>
            <input value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={!file || uploading}>
              {uploading ? "Uploading..." : "Upload"}
            </button>
          </div>
        </form>
      </div>

      <div>
        <p className="portal-section-heading">Your documents</p>
        {documents === null ? (
          <p className="portal-empty">Loading...</p>
        ) : documents.length ? (
          <div style={{ display: "grid", gap: ".6rem", marginTop: ".6rem" }}>
            {documents.map((document) => (
              <div key={document.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>{document.title}</strong>
                    <div className="portal-empty">
                      {formatDate(document.uploadedAt)} · {formatSize(document.sizeBytes)}
                      {document.uploadedByPatient ? " · Uploaded by you" : " · Shared by your clinic"}
                    </div>
                    {document.description && <div className="portal-empty">{document.description}</div>}
                  </div>
                </header>
                <div className="button-row">
                  <a className="secondary-button" href={api.portalDocumentDownloadUrl(document.id)} target="_blank" rel="noreferrer">
                    Download
                  </a>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="portal-empty">No documents shared yet.</p>
        )}
      </div>
    </>
  );
}
