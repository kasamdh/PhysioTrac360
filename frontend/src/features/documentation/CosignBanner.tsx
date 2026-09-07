import { useState } from "react";
import { ShieldAlert } from "lucide-react";

import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";

interface CosignBannerProps {
  canCosign: boolean;
  onCosign: () => Promise<void>;
}

export function CosignBanner({ canCosign, onCosign }: CosignBannerProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onCosign();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to cosign this note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />
        <div className="flex-1">
          <p className="m-0 text-sm font-medium text-amber-800">
            This note was signed by the treating PTA and is awaiting a supervising cosignature before it is final.
          </p>
          {error && <p className="mt-2 text-sm font-medium text-red-700">{error}</p>}
          {canCosign && (
            <Button type="button" size="sm" className="mt-3" disabled={busy} onClick={() => void confirm()}>
              {busy ? "Cosigning..." : "Cosign Note"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
