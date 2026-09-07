import { api } from "../api/client";
import type { ManagedClient } from "../api/types";
import { StatusActionDialog } from "./StatusActionDialog";

interface SuspendClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onSuspended: () => Promise<void>;
}

export function SuspendClientDialog({ client, onClose, onSuspended }: SuspendClientDialogProps) {
  async function confirm(reason: string) {
    await api.setManagedClientStatus(client.clientNumber, "suspend", reason);
    await onSuspended();
  }

  return (
    <StatusActionDialog
      eyebrow={`Client #${client.clientNumber}`}
      title={`Suspend ${client.clientName}?`}
      body={`Suspending this client will immediately prevent all users, staff, therapists, and patients associated with ${client.clientName} from accessing the system. No data will be deleted.`}
      confirmLabel="Suspend client"
      destructive
      requireReason
      reasonLabel="Suspension reason"
      onClose={onClose}
      onConfirm={confirm}
    />
  );
}
