import { useEffect, useState } from "react";
import { Search } from "lucide-react";

import { ApiError, api } from "../api/client";
import type { CredentialDashboardRow } from "../api/types";
import { formatDate } from "../lib/format";
import { Input } from "@/components/ui/input";
import { LicenseBadge } from "@/components/ui/license-banner";
import { StatusTabs } from "@/components/ui/status-tabs";
import { Button } from "@/components/ui/button";

const BUCKET_TABS = [
  { value: "attention", label: "Needs Attention" },
  { value: "expired", label: "Expired" },
  { value: "critical", label: "Critical" },
  { value: "expiring_soon", label: "Expiring Soon" },
  { value: "all", label: "All Licenses" },
];

export function CredentialDashboardPage() {
  const [rows, setRows] = useState<CredentialDashboardRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState("50");
  const [query, setQuery] = useState("");
  const [bucket, setBucket] = useState("attention");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const filters: Record<string, string> = { page: String(page), pageSize };
      if (query) filters.q = query;
      if (bucket === "all") filters.includeValid = "true";
      else if (bucket !== "attention") filters.bucket = bucket;
      const result = await api.credentialDashboard(filters);
      setRows(result.licenses);
      setTotal(result.total);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the credential dashboard.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setPage(1);
  }, [query, bucket]);
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, bucket, page]);

  const pageCount = Math.max(1, Math.ceil(total / Number(pageSize)));

  return (
    <div className="mx-auto max-w-[1400px] p-6 md:p-8">
      <header className="mb-6">
        <p className="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-primary-deep">Super Admin · Credentials</p>
        <h1 className="m-0 text-2xl font-bold tracking-tight text-foreground md:text-3xl">Credential Dashboard</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground md:text-base">
          PT/PTA license expirations across every organization. A license that has already expired automatically
          suspends that provider's clinical access — the Account column reflects that.
        </p>
      </header>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <StatusTabs tabs={BUCKET_TABS} value={bucket} onChange={setBucket} />
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Provider, license #, or organization"
            className="h-11 w-72 pl-9 text-sm"
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-white">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">License Type</th>
                <th className="px-4 py-3">License Number</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Expiration Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Required Action</th>
                <th className="px-4 py-3">Account</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={row.licenseId} className="hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-foreground">{row.providerName}</div>
                    <div className="text-xs text-muted-foreground">{row.providerRoleLabel}</div>
                  </td>
                  <td className="px-4 py-3 text-foreground">
                    {row.clientNumber !== null ? `#${row.clientNumber} ` : ""}
                    {row.clientName}
                  </td>
                  <td className="px-4 py-3 text-foreground">{row.location || "—"}</td>
                  <td className="px-4 py-3 text-foreground">{row.licenseType || "—"}</td>
                  <td className="px-4 py-3 text-foreground">{row.licenseNumber}</td>
                  <td className="px-4 py-3 text-foreground">{row.issuingState}</td>
                  <td className="px-4 py-3 text-foreground">
                    {formatDate(row.expiresAt, { month: "short", day: "numeric", year: "numeric" })}
                  </td>
                  <td className="px-4 py-3"><LicenseBadge status={row.colorBucket} /></td>
                  <td className="px-4 py-3 text-foreground">{row.requiredAction}</td>
                  <td className="px-4 py-3">
                    {row.accountStatus === "active" ? (
                      <span className="text-muted-foreground">Active</span>
                    ) : (
                      <span className="font-semibold text-destructive">{row.accountStatus.replace(/_/g, " ")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!loading && !rows.length && (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            {bucket === "attention" ? "No licenses currently need attention." : "No licenses match this search."}
          </p>
        )}
        {loading && <p className="px-4 py-10 text-center text-sm text-muted-foreground">Loading…</p>}
      </div>

      <div className="mt-4 flex items-center justify-center gap-3 text-sm">
        <Button variant="secondary" size="sm" className="h-9" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
          Previous
        </Button>
        <span className="text-muted-foreground">
          Page {page} of {pageCount} · {total} license{total === 1 ? "" : "s"}
        </span>
        <Button variant="secondary" size="sm" className="h-9" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
