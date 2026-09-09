import { FormEvent, useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { ApiError, api } from "../api/client";
import type { WorkspaceUser } from "../api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface LoginScreenProps {
  onAuthenticated: (user: WorkspaceUser) => void;
  noticeMessage?: string;
}

export function LoginScreen({ onAuthenticated, noticeMessage }: LoginScreenProps) {
  const portalSlug = window.location.pathname.split("/").filter(Boolean)[0] || "";
  const [facilityName, setFacilityName] = useState("Facility name");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(noticeMessage || "");
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    if (!portalSlug || portalSlug === "app") return;
    api.facility(portalSlug).then((facility) => setFacilityName(facility.name)).catch(() => undefined);
  }, [portalSlug]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      onAuthenticated(await api.login(username, password, portalSlug));
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const showFacilityBox = Boolean(portalSlug) && portalSlug !== "app";

  return (
    <main className="flex min-h-screen flex-col bg-white font-sans md:flex-row">
      <div className="relative flex flex-1 flex-col items-center justify-center gap-6 overflow-hidden bg-gradient-to-br from-[#0a2e29] via-[#0f3d38] to-[#0a2622] px-6 py-12 text-center md:basis-1/2 md:px-10">
        <div
          className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-primary/30 blur-3xl"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -bottom-32 -right-16 h-80 w-80 rounded-full bg-primary-soft/20 blur-3xl"
          aria-hidden="true"
        />

        <div
          className="relative grid h-20 w-20 place-items-center rounded-2xl border border-white/15 bg-white/10 text-white shadow-[0_20px_50px_rgb(0_0_0_/_35%)] backdrop-blur-sm md:h-24 md:w-24 md:rounded-3xl"
          aria-hidden="true"
        >
          <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-9 w-9 md:h-11 md:w-11">
            <path
              d="M6 34h9l5-14 9 28 8-20 5 6h16"
              stroke="currentColor"
              strokeWidth="4.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        <div className="relative">
          <p className="m-0 text-[2rem] font-semibold tracking-[-0.02em] text-white md:text-[2.5rem]">
            PhysioTrac<span className="text-primary-soft">360</span>
          </p>
          <p className="mx-auto mt-2 max-w-[320px] text-[1.0625rem] font-normal text-white/70">
            Complete practice operations — scheduling, documentation, and billing in one connected workspace.
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center bg-[#f7f8f8] px-5 py-12 md:basis-1/2 md:px-10">
        <Card
          aria-labelledby="login-title"
          className="w-full max-w-[420px] gap-0 rounded-2xl border-0 bg-white p-7 shadow-[0_24px_60px_-12px_rgb(15_23_42_/_18%)] md:p-9"
        >
          <div className="mb-6">
            <h1 id="login-title" className="m-0 text-[1.625rem] font-semibold tracking-[-0.01em] text-[#172127]">
              Sign in
            </h1>
            <p className="m-0 mt-1.5 text-[0.9375rem] text-[#6b7680]">
              Enter your credentials to access your workspace.
            </p>
          </div>

          <div className="grid gap-5">
            {error && (
              <p
                role="alert"
                className="m-0 rounded-lg border border-[#f3c3c9] bg-[#fdecec] px-4 py-3 text-[0.9375rem] font-medium leading-snug text-[#a52338]"
              >
                {error}
              </p>
            )}

            {showFacilityBox && (
              <div>
                <span id="signin-org-label" className="mb-1.5 block text-sm font-medium text-[#33414d]">
                  Organization
                </span>
                <div
                  role="note"
                  aria-labelledby="signin-org-label"
                  className="flex min-h-[52px] items-center rounded-lg bg-[#f2f4f4] px-4 text-[1rem] font-medium text-[#37454f]"
                >
                  {facilityName}
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="grid gap-4">
              <div>
                <Label htmlFor="signin-username">Login User Id</Label>
                <Input
                  id="signin-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Enter your user ID"
                  autoComplete="username"
                  aria-invalid={Boolean(error)}
                  required
                  className="h-12 rounded-lg text-base placeholder:text-[0.9375rem]"
                />
              </div>

              <div>
                <Label htmlFor="signin-password">Login Password</Label>
                <div className="relative">
                  <Input
                    id="signin-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    type={showPassword ? "text" : "password"}
                    placeholder="Enter your password"
                    autoComplete="current-password"
                    required
                    className="h-12 rounded-lg pr-11 text-base placeholder:text-[0.9375rem]"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                    className="absolute inset-y-0 right-0 grid w-11 place-items-center border-0 bg-transparent text-[#6b7680] hover:text-[#33414d]"
                  >
                    {showPassword ? <EyeOff className="h-[18px] w-[18px]" /> : <Eye className="h-[18px] w-[18px]" />}
                  </button>
                </div>
              </div>

              <Button
                type="submit"
                disabled={submitting}
                className="mt-1 h-12 w-full rounded-lg px-8 text-[1.0625rem] font-medium"
              >
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </div>
        </Card>

        <p className="mt-8 text-center text-[0.8125rem] text-[#8b98a3]">
          PhysioTrac360 &copy; {new Date().getFullYear()} PhysioTrac360, Inc. All rights reserved. Confidential.
        </p>
      </div>
    </main>
  );
}
