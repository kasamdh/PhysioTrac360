import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { WorkspaceUser } from "../api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface LoginScreenProps {
  onAuthenticated: (user: WorkspaceUser) => void;
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const portalSlug = window.location.pathname.split("/").filter(Boolean)[0] || "";
  const [facilityName, setFacilityName] = useState("Facility name");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
    <main className="flex min-h-screen flex-col bg-white font-sans">
      <header className="flex flex-none items-center gap-[0.7rem] bg-gradient-to-r from-[#0b2b27] to-primary-deep px-[1.4rem] py-[0.8rem] text-white">
        <span
          className="grid h-[34px] w-[34px] place-items-center rounded-[9px] border border-white/30 bg-white/16 text-[0.8rem] font-semibold tracking-[0.04em]"
          aria-hidden="true"
        >
          PT
        </span>
        <strong className="text-[1.05rem] font-semibold tracking-[-0.01em]">
          PhysioTrac<em className="text-primary-soft">360</em>
        </strong>
      </header>

      <div className="flex flex-1 flex-col md:flex-row">
        <div className="flex flex-1 flex-col items-center justify-center gap-[0.6rem] px-6 pb-4 pt-8 text-center md:basis-[55%] md:p-10">
          <div
            className="mb-[0.6rem] grid h-24 w-24 place-items-center rounded-3xl bg-gradient-to-br from-primary to-primary-deep text-white shadow-[0_20px_40px_rgb(13_148_136_/_24%)] md:h-[140px] md:w-[140px] md:rounded-[32px]"
            aria-hidden="true"
          >
            <svg
              viewBox="0 0 64 64"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="h-[46px] w-[46px] md:h-[68px] md:w-[68px]"
            >
              <path
                d="M6 34h9l5-14 9 28 8-20 5 6h16"
                stroke="currentColor"
                strokeWidth="4.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className="text-[1.875rem] font-semibold tracking-[-0.02em] text-[#172127] md:text-[2.125rem] lg:text-[2.375rem]">
            PhysioTrac<span className="text-primary-deep italic">360</span>
          </div>
          <p className="m-0 text-[1.125rem] font-normal text-[#56626f]">Complete practice operations</p>
        </div>

        <div className="flex flex-1 flex-col items-center justify-center gap-5 border-t border-[#dde6e4] bg-[#eef2f1] px-5 py-8 md:basis-[45%] md:border-l md:border-t-0 md:px-8 md:py-10">
          <p
            id="login-title"
            className="m-0 text-[1.875rem] font-semibold tracking-[-0.02em] text-[#172127] md:text-[2.125rem] lg:text-[2.375rem]"
          >
            PhysioTrac<em className="text-primary-deep italic">360</em>
          </p>
          <Card
            aria-labelledby="login-title"
            className="max-w-[440px] p-7 shadow-[0_18px_40px_rgb(15_23_42_/_12%)] md:p-9"
          >
            {error && (
              <p
                role="alert"
                className="m-0 rounded-md border border-[#f3c3c9] bg-[#fdecec] px-4 py-3 text-[1.0625rem] font-medium leading-snug text-[#a52338]"
              >
                {error}
              </p>
            )}

            {showFacilityBox && (
              <div>
                <span
                  id="signin-org-label"
                  className="mb-[0.4rem] block text-[1.0625rem] font-medium text-[#33414d]"
                >
                  Organization
                </span>
                <div
                  role="note"
                  aria-labelledby="signin-org-label"
                  className="flex min-h-[54px] items-center rounded-md bg-white px-4 text-[1.125rem] font-medium text-[#37454f] shadow-[inset_0_0_0_1px_#c7d0ce]"
                >
                  {facilityName}
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="grid gap-[1.1rem]">
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
                  className="text-base placeholder:text-[1.0625rem] md:text-[1.0625rem] lg:text-[1.125rem]"
                />
              </div>

              <div>
                <Label htmlFor="signin-password">Login Password</Label>
                <Input
                  id="signin-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  required
                  className="text-base placeholder:text-[1.0625rem] md:text-[1.0625rem] lg:text-[1.125rem]"
                />
              </div>

              <Button
                type="submit"
                disabled={submitting}
                className="mt-[0.3rem] h-14 w-full px-8 text-[1.125rem] font-medium md:text-[1.1875rem] lg:text-[1.25rem]"
              >
                {submitting ? "Signing in…" : "Login"}
              </Button>
            </form>
          </Card>
        </div>
      </div>

      <footer className="flex-none px-4 py-4 text-center text-[0.9375rem] text-[#8b98a3]">
        PhysioTrac360 &copy; {new Date().getFullYear()} PhysioTrac360, Inc. All rights reserved. Confidential.
      </footer>
    </main>
  );
}
