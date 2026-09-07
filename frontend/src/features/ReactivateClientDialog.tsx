import { api } from "../api/client";
import type { ManagedClient } from "../api/types";
import { StatusActionDialog } from "./StatusActionDialog";

interface ReactivateClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onReactivated: () => Promise<void>;
}

export function ReactivateClientDialog({ client, onClose, onReactivated }: ReactivateClientDialogProps) {
  async function confirm() {
    await api.setManagedClientStatus(client.clientNumber, "activate");
    await onReactivated();
  }

  return (
    <StatusActionDialog
      eyebrow={`Client #${client.clientNumber}`}
      title={`Reactivate ${client.clientName}?`}
      body="Reactivating this client restores system access for its administrator, staff, therapists, and patients according to their previous permissions."
      confirmLabel="Reactivate client"
      onClose={onClose}
      onConfirm={confirm}
    />
  );
}
