import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { GlobalAuditEvent, SuperAdminDashboard, WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";
import { MetricCard } from "@/components/ui/metric-card";
import { formatDateTime } from "../lib/format";

interface SuperAdminHomePageProps {
  user: WorkspaceUser;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
}

function IconAdministration() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="3.1" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4M17.7 17.7l-1.4-1.4M7.7 7.7 6.3 6.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ActivityRow({ event }: { event: GlobalAuditEvent }) {
  return (
    <li className="flex items-start justify-between gap-3 border-t border-[#edf0f4] py-2.5 first:border-t-0 first:pt-0">
      <div className="min-w-0">
        <p className="m-0 truncate text-sm font-semibold text-[#1c1f23]">{event.action.replace(/_/g, " ")}</p>
        <p className="m-0 truncate text-[0.8125rem] text-[#6B7280]">
          {event.actor} {event.clientName ? `· ${event.clientName}` : ""}
        </p>
      </div>
      <time className="shrink-0 text-[0.8125rem] text-[#6B7280]">{formatDateTime(event.createdAt)}</time>
    </li>
  );
}

export function SuperAdminHomePage({ user, onNavigate, onLogout }: SuperAdminHomePageProps) {
  const [data, setData] = useState<SuperAdminDashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api
      .superAdminDashboard()
      .then((result) => active && setData(result))
      .catch((requestError) => active && setError(requestError instanceof ApiError ? requestError.message : "Unable to load the dashboard."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const credentialTotal = data
    ? data.credentialAlerts.expired + data.credentialAlerts.critical + data.credentialAlerts.expiring_soon
    : 0;
  const maxTrendCount = data ? Math.max(1, ...data.failedLoginTrend.map((row) => row.count)) : 1;

  return (
    <div className="flex min-h-screen flex-col bg-white">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} brandLabel="Source Motion PT" />
      <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-6 pt-10">
        <header className="mb-7 text-center">
          <h1 className="m-0 text-[clamp(1.75rem,3vw,2.125rem)] font-bold tracking-[-0.02em] text-[#172127]">
            Source Motion PT
          </h1>
        </header>

        {loading && <p className="text-center text-sm text-[#6B7280]">Loading dashboard…</p>}
        {error && (
          <p role="alert" className="mx-auto mb-6 max-w-lg rounded-md border border-red-200 bg-red-50 px-4 py-3 text-center text-sm font-medium text-red-700">
            {error}
          </p>
        )}

        {data && (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 min-[700px]:grid-cols-3 min-[1000px]:grid-cols-5">
              <MetricCard label="Total Organizations" value={data.organizations.total} onClick={() => onNavigate("clients")} />
              <MetricCard label="Active Organizations" value={data.organizations.active} tone="green" onClick={() => onNavigate("clients")} />
              <MetricCard label="Suspended Organizations" value={data.organizations.suspended} tone="amber" onClick={() => onNavigate("clients")} />
              <MetricCard label="Archived Organizations" value={data.organizations.archived} onClick={() => onNavigate("clients")} />
              <MetricCard label="Total Locations" value={data.locationsTotal} />
              <MetricCard label="Total Users" value={data.users.total} onClick={() => onNavigate("users")} />
              <MetricCard label="Active PTs" value={data.users.activePts} tone="blue" onClick={() => onNavigate("users")} />
              <MetricCard label="Active PTAs" value={data.users.activePtas} tone="blue" onClick={() => onNavigate("users")} />
              <MetricCard
                label="Credential Expiration Alerts"
                value={credentialTotal}
                tone={credentialTotal > 0 ? "crimson" : "neutral"}
                detail={`${data.credentialAlerts.expired} expired`}
                onClick={() => onNavigate("credentials")}
              />
              <MetricCard label="Total Patients" value={data.patientsTotal} />
            </div>

            <div className="mb-10 grid grid-cols-1 gap-6 min-[900px]:grid-cols-2">
              <section className="rounded-[14px] border border-border p-5">
                <h2 className="m-0 mb-3 text-lg font-bold text-[#1c1f23]">Subscription Status</h2>
                {Object.keys(data.subscriptionTiers).length === 0 ? (
                  <p className="m-0 text-sm text-[#6B7280]">No active organizations yet.</p>
                ) : (
                  <ul className="m-0 list-none p-0">
                    {Object.entries(data.subscriptionTiers).map(([tier, count]) => (
                      <li key={tier} className="flex items-center justify-between gap-3 border-t border-[#edf0f4] py-2.5 first:border-t-0 first:pt-0">
                        <span className="text-sm font-semibold capitalize text-[#1c1f23]">{tier}</span>
                        <span className="text-sm text-[#6B7280]">{count} organization{count === 1 ? "" : "s"}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-[14px] border border-border p-5">
                <h2 className="m-0 mb-3 text-lg font-bold text-[#1c1f23]">Recent Organizations</h2>
                {data.recentOrganizations.length === 0 ? (
                  <p className="m-0 text-sm text-[#6B7280]">No organizations yet.</p>
                ) : (
                  <ul className="m-0 list-none p-0">
                    {data.recentOrganizations.map((org) => (
                      <li key={org.clientNumber} className="flex items-center justify-between gap-3 border-t border-[#edf0f4] py-2.5 first:border-t-0 first:pt-0">
                        <div className="min-w-0">
                          <p className="m-0 truncate text-sm font-semibold text-[#1c1f23]">
                            #{org.clientNumber} — {org.clientName}
                          </p>
                          <p className="m-0 text-[0.8125rem] text-[#6B7280]">{formatDateTime(org.createdAt)}</p>
                        </div>
                        <span className="shrink-0 rounded-full bg-[#F7F7F8] px-2.5 py-1 text-xs font-semibold text-[#1c1f23]">
                          {org.statusLabel}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-[14px] border border-border p-5">
                <h2 className="m-0 mb-3 text-lg font-bold text-[#1c1f23]">Recent User Activity</h2>
                {data.recentUserActivity.length === 0 ? (
                  <p className="m-0 text-sm text-[#6B7280]">No recent sign-in activity.</p>
                ) : (
                  <ul className="m-0 list-none p-0">
                    {data.recentUserActivity.map((event) => (
                      <ActivityRow key={event.id} event={event} />
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-[14px] border border-border p-5">
                <h2 className="m-0 mb-3 text-lg font-bold text-[#1c1f23]">Recent Audit Events</h2>
                {data.recentAuditEvents.length === 0 ? (
                  <p className="m-0 text-sm text-[#6B7280]">No audit events yet.</p>
                ) : (
                  <ul className="m-0 list-none p-0">
                    {data.recentAuditEvents.map((event) => (
                      <ActivityRow key={event.id} event={event} />
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-[14px] border border-border p-5">
                <h2 className="m-0 mb-1 text-lg font-bold text-[#1c1f23]">Failed Login Trend</h2>
                <p className="m-0 mb-3 text-[0.8125rem] text-[#6B7280]">Last 7 days, across every organization.</p>
                {data.failedLoginTrend.length === 0 ? (
                  <p className="m-0 text-sm text-[#6B7280]">No failed sign-in attempts recorded.</p>
                ) : (
                  <div className="flex h-24 items-end gap-2">
                    {data.failedLoginTrend.map((row) => (
                      <div key={row.date} className="flex flex-1 flex-col items-center gap-1">
                        <div
                          className="w-full rounded-t-[4px] bg-primary"
                          style={{ height: `${Math.max(6, (row.count / maxTrendCount) * 80)}px` }}
                          title={`${row.count} on ${row.date}`}
                        />
                        <span className="text-[0.6875rem] text-[#6B7280]">{row.date.slice(5)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </>
        )}

        <nav aria-label="Platform administration modules" className="mb-10">
          <button
            type="button"
            onClick={() => onNavigate("admin-hub")}
            className="group flex min-h-[110px] w-full items-center gap-4 rounded-[14px] border-0 bg-gradient-to-br from-primary to-primary-deep p-4 text-left text-white shadow-[0_10px_20px_rgb(176_0_32_/_18%)] transition-all hover:brightness-105 hover:-translate-y-px"
          >
            <span className="grid h-[92px] w-[92px] shrink-0 place-items-center rounded-[20px] bg-white/15 text-white [&_svg]:h-11 [&_svg]:w-11 max-[900px]:h-20 max-[900px]:w-20 max-[900px]:[&_svg]:h-[38px] max-[900px]:[&_svg]:w-[38px]">
              <IconAdministration />
            </span>
            <span className="grid min-w-0 gap-1">
              <strong className="text-2xl font-semibold tracking-[-0.01em] text-white max-[900px]:text-[1.375rem]">
                Administration
              </strong>
              <small className="text-base leading-snug text-white/85 max-[620px]:text-[0.9375rem]">
                Manage clients, platform users, and account settings.
              </small>
            </span>
          </button>
        </nav>

        <footer className="mt-auto flex justify-center gap-[0.6rem] border-t border-[#ece5df] py-6 text-sm text-[#97a0a8]">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} Source Motion Physical Therapy LLC. All rights reserved.</span>
        </footer>
      </div>
    </div>
  );
}
