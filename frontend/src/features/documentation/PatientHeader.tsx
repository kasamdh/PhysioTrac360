import { AlertTriangle } from "lucide-react";

import type { NoteDetail, Patient } from "@/api/types";
import { formatDate } from "@/lib/format";

function calculateAge(dateOfBirth: string): number {
  const dob = new Date(dateOfBirth.includes("T") ? dateOfBirth : `${dateOfBirth}T12:00:00`);
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const monthDiff = today.getMonth() - dob.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dob.getDate())) age -= 1;
  return age;
}

interface PatientHeaderProps {
  patient: Patient & { diagnoses: string; precautions: string };
  note: NoteDetail;
}

export function PatientHeader({ patient, note }: PatientHeaderProps) {
  return (
    <div className="mb-6 rounded-xl border border-border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="m-0 text-xl font-bold text-foreground md:text-2xl">{patient.fullName}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            DOB {formatDate(patient.dateOfBirth)} ({calculateAge(patient.dateOfBirth)}y) · MRN {patient.medicalRecordNumber}
            {" · "}Visit {formatDate(note.serviceDate)}
          </p>
        </div>
        <div className="text-right text-sm text-muted-foreground">
          <div>{note.therapistName}</div>
          <div>{note.noteTypeLabel}</div>
        </div>
      </div>

      {patient.diagnoses && (
        <p className="mt-3 text-sm text-foreground">
          <span className="font-semibold text-muted-foreground">Diagnosis: </span>
          {patient.diagnoses}
        </p>
      )}

      {patient.precautions && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{patient.precautions}</span>
        </div>
      )}
    </div>
  );
}
