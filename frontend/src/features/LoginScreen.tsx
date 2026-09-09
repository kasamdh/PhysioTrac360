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

  // Sizing/radius-only overrides — no color overrides needed anymore.
  // --color-primary (tailwind.css) is now the Source Motion red app-wide,
  // so the shared Input/Button components already render in-brand here,
  // the same as every other page.
  const inputClass = "h-14 rounded-[10px] text-[1.0625rem]";

  return (
    <main className="flex min-h-screen flex-col bg-white font-sans md:flex-row">
      <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-[#F7F7F8] px-6 py-12 text-center md:basis-1/2 md:px-10">
        <img
          src={`${import.meta.env.BASE_URL}assets/source-motion-logo.png`}
          alt="Source Motion Physical Therapy"
          className="h-auto w-[85%] max-w-[320px] object-contain md:w-4/5 md:max-w-[650px]"
        />
        <p className="max-w-[420px] text-[1.125rem] font-normal text-[#6B7280]">
          Complete practice operations — scheduling, documentation, and billing in one connected workspace.
        </p>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center bg-white px-5 py-12 md:basis-1/2 md:px-10">
        <Card
          aria-labelledby="login-title"
          className="w-full max-w-[460px] gap-0 rounded-xl border border-[#E5E7EB] bg-white p-8 shadow-[0_8px_24px_rgba(31,31,31,0.06)] md:p-10"
        >
          <div className="mb-7">
            <h1
              id="login-title"
              className="m-0 text-[clamp(2.2rem,4vw,2.75rem)] font-bold tracking-[-0.01em] text-[#222222]"
            >
              Welcome Back
            </h1>
            <p className="m-0 mt-2 text-[1.125rem] text-[#6B7280]">
              Sign in to your Source Motion PT account.
            </p>
          </div>

          <div className="grid gap-5">
            {error && (
              <p
                role="alert"
                className="m-0 rounded-lg border border-[#f3c3c9] bg-[#fdecec] px-4 py-3 text-[1rem] font-medium leading-snug text-[#a52338]"
              >
                {error}
              </p>
            )}

            {showFacilityBox && (
              <div>
                <span id="signin-org-label" className="mb-1.5 block text-base font-medium text-[#33414d]">
                  Organization
                </span>
                <div
                  role="note"
                  aria-labelledby="signin-org-label"
                  className="flex min-h-[52px] items-center rounded-lg bg-[#F7F7F8] px-4 text-[1.0625rem] font-medium text-[#37454f]"
                >
                  {facilityName}
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="grid gap-4">
              <div>
                <Label htmlFor="signin-username" className="text-[1.0625rem]">Login User Id</Label>
                <Input
                  id="signin-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Enter your user ID"
                  autoComplete="username"
                  aria-invalid={Boolean(error)}
                  required
                  className={inputClass}
                />
              </div>

              <div>
                <Label htmlFor="signin-password" className="text-[1.0625rem]">Login Password</Label>
                <div className="relative">
                  <Input
                    id="signin-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    type={showPassword ? "text" : "password"}
                    placeholder="Enter your password"
                    autoComplete="current-password"
                    required
                    className={`${inputClass} pr-11`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                    className="absolute inset-y-0 right-0 grid w-11 place-items-center border-0 bg-transparent text-[#6B7280] hover:text-[#222222]"
                  >
                    {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                  </button>
                </div>
              </div>

              <Button
                type="submit"
                disabled={submitting}
                className="mt-1 h-14 w-full rounded-[10px] text-[1.1875rem] font-semibold"
              >
                {submitting ? "Signing in…" : "Sign In"}
              </Button>
            </form>
          </div>
        </Card>

        <footer className="mt-8 flex flex-col items-center gap-1.5 text-center text-[0.9375rem] text-[#6B7280]">
          <p className="m-0">&copy; {new Date().getFullYear()} Source Motion Physical Therapy LLC. All rights reserved.</p>
          <p className="m-0 flex items-center gap-2">
            <span>Privacy</span>
            <span aria-hidden="true">|</span>
            <span>Terms</span>
            <span aria-hidden="true">|</span>
            <span>Support</span>
          </p>
        </footer>
      </div>
    </main>
  );
}
