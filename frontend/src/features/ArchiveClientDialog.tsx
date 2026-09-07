import { api } from "../api/client";
import type { ManagedClient } from "../api/types";
import { StatusActionDialog } from "./StatusActionDialog";

interface ArchiveClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onArchived: () => Promise<void>;
}

export function ArchiveClientDialog({ client, onClose, onArchived }: ArchiveClientDialogProps) {
  async function confirm(reason: string) {
    await api.archiveManagedClient(client.clientNumber, reason);
    await onArchived();
  }

  return (
    <StatusActionDialog
      eyebrow={`Client #${client.clientNumber}`}
      title={`Archive ${client.clientName}?`}
      body={`Archiving is permanent for this workspace and immediately blocks access for every user, therapist, and patient associated with ${client.clientName}. No records, notes, or audit history are deleted — an archived client can be restored by support if needed.`}
      confirmLabel="Archive client"
      destructive
      requireReason
      reasonLabel="Archive reason"
      onClose={onClose}
      onConfirm={confirm}
    />
  );
}
