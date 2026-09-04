"""Forms intentionally exclude tenant, actor, and signature fields."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from PIL import Image, UnidentifiedImageError

from .models import (
    Appointment,
    ClinicalNote,
    Consent,
    FunctionalGoal,
    HomeProgram,
    IntakeSubmission,
    Location,
    NoteAddendum,
    OutcomeScore,
    PaymentRecord,
    Patient,
    Organization,
    Provider,
    SecureMessage,
    Superbill,
    User,
    VoiceCapture,
)
from .services import outcome_measure_defaults


class StyledFormMixin:
    """Apply a consistent, accessible style without relying on client-side code."""

    def _style_fields(self):
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "field-input")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "field-check"


class PatientForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "phone",
            "email",
            "address",
            "emergency_contact",
            "diagnoses",
            "precautions",
            "assigned_therapist",
            "status",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "diagnoses": forms.Textarea(attrs={"rows": 3}),
            "precautions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        if organization:
            self.fields["assigned_therapist"].queryset = User.objects.filter(
                organization=organization,
                is_active=True,
                role__in=[
                    User.Role.ADMIN,
                    User.Role.DIRECTOR,
                    User.Role.THERAPIST,
                    User.Role.ASSISTANT,
                ],
            ).order_by("last_name", "first_name")


class AppointmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "patient",
            "therapist",
            "provider",
            "kind",
            "status",
            "starts_at",
            "ends_at",
            "location",
            "location_detail",
            "is_home_visit",
            "private_notes",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "private_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, organization=None, patient_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        if patient_queryset is not None:
            self.fields["patient"].queryset = patient_queryset
        if organization:
            self.fields["therapist"].queryset = User.objects.filter(
                organization=organization,
                is_active=True,
                role__in=[
                    User.Role.ADMIN,
                    User.Role.DIRECTOR,
                    User.Role.THERAPIST,
                    User.Role.ASSISTANT,
                ],
            ).order_by("last_name", "first_name")
            self.fields["provider"].queryset = Provider.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by("last_name", "first_name")
            self.fields["location_detail"].queryset = Location.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by("name")


class ClinicalNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ClinicalNote
        fields = [
            "appointment",
            "note_type",
            "service_date",
            "diagnosis_snapshot",
            "precautions_snapshot",
            "subjective",
            "objective",
            "interventions",
            "assessment",
            "plan",
            "plan_of_care_start",
            "plan_of_care_end",
            "frequency_per_week",
            "duration_weeks",
            "reassessment_due",
        ]
        widgets = {
            "service_date": forms.DateInput(attrs={"type": "date"}),
            "plan_of_care_start": forms.DateInput(attrs={"type": "date"}),
            "plan_of_care_end": forms.DateInput(attrs={"type": "date"}),
            "reassessment_due": forms.DateInput(attrs={"type": "date"}),
            "diagnosis_snapshot": forms.Textarea(attrs={"rows": 2}),
            "precautions_snapshot": forms.Textarea(attrs={"rows": 2}),
            "subjective": forms.Textarea(attrs={"rows": 4}),
            "objective": forms.Textarea(attrs={"rows": 5}),
            "interventions": forms.Textarea(attrs={"rows": 4}),
            "assessment": forms.Textarea(attrs={"rows": 4}),
            "plan": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self.patient = patient
        if patient:
            appointment_filter = Q(clinical_note__isnull=True)
            if self.instance and self.instance.appointment_id:
                appointment_filter |= Q(pk=self.instance.appointment_id)
            self.fields["appointment"].queryset = patient.appointments.filter(
                appointment_filter
            )
            if not self.instance.pk:
                self.initial.setdefault("diagnosis_snapshot", patient.diagnoses)
                self.initial.setdefault("precautions_snapshot", patient.precautions)

    def clean_appointment(self):
        appointment = self.cleaned_data.get("appointment")
        if appointment and self.patient and appointment.patient_id != self.patient.id:
            raise ValidationError("Only an appointment for this patient may be linked.")
        return appointment


class NoteAddendumForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = NoteAddendum
        fields = ["reason", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class FunctionalGoalForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FunctionalGoal
        fields = [
            "functional_limitation",
            "functional_task",
            "baseline_value",
            "target_value",
            "current_value",
            "unit",
            "measurement_method",
            "target_date",
            "suggested_wording",
        ]
        widgets = {
            "functional_limitation": forms.Textarea(attrs={"rows": 3}),
            "target_date": forms.DateInput(attrs={"type": "date"}),
            "suggested_wording": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self.fields["current_value"].required = False


class OutcomeScoreForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OutcomeScore
        fields = ["measure", "measured_on", "score", "maximum_score", "notes"]
        widgets = {
            "measured_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self.fields["maximum_score"].required = False

    def clean(self):
        cleaned = super().clean()
        measure = cleaned.get("measure")
        if measure and not cleaned.get("maximum_score"):
            default = outcome_measure_defaults(measure).get("maximum")
            if default is not None:
                cleaned["maximum_score"] = default
        return cleaned


class VoiceCaptureForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = VoiceCapture
        fields = ["consent_confirmed", "duration_seconds", "transcript"]
        widgets = {
            "transcript": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": "Paste the reviewed transcript. Do not save raw audio here.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def clean_consent_confirmed(self):
        value = self.cleaned_data["consent_confirmed"]
        if not value:
            raise ValidationError("Confirm applicable patient consent before saving a transcript.")
        return value


class SecureMessageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SecureMessage
        fields = ["recipient", "subject", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        if organization:
            self.fields["recipient"].queryset = User.objects.filter(
                organization=organization, is_active=True
            ).order_by("last_name", "first_name")


class HomeProgramForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HomeProgram
        fields = ["title", "diagnosis_context", "precautions", "patient_instructions"]
        widgets = {
            "diagnosis_context": forms.Textarea(attrs={"rows": 3}),
            "precautions": forms.Textarea(attrs={"rows": 3}),
            "patient_instructions": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class ConsentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Consent
        fields = ["kind", "document_version", "signature_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self.fields["document_version"].initial = "v1"


class IntakeCaptureForm(StyledFormMixin, forms.Form):
    form_version = forms.CharField(initial="v1", max_length=40)
    chief_complaint = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    functional_goals = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    relevant_history = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 4})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def as_answers(self):
        return {
            "chief_complaint": self.cleaned_data["chief_complaint"],
            "functional_goals": self.cleaned_data["functional_goals"],
            "relevant_history": self.cleaned_data["relevant_history"],
        }


class SuperbillForm(StyledFormMixin, forms.ModelForm):
    codes = forms.CharField(
        label="CPT / service codes",
        help_text="Separate codes with commas. Verify coding and payer requirements.",
    )

    class Meta:
        model = Superbill
        fields = ["service_date", "codes", "amount", "status", "payment_processor_reference"]
        widgets = {
            "service_date": forms.DateInput(attrs={"type": "date"}),
            "payment_processor_reference": forms.TextInput(
                attrs={"placeholder": "Approved processor reference only"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        if self.instance and self.instance.pk:
            self.fields["codes"].initial = ", ".join(self.instance.codes)

    def clean_codes(self):
        codes = [code.strip().upper() for code in self.cleaned_data["codes"].split(",")]
        codes = [code for code in codes if code]
        if not codes:
            raise ValidationError("Enter at least one service code.")
        return codes

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.codes = self.cleaned_data["codes"]
        if commit:
            instance.save()
        return instance


class PaymentRecordForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PaymentRecord
        fields = [
            "superbill",
            "amount",
            "received_on",
            "status",
            "payment_processor_reference",
        ]
        widgets = {
            "received_on": forms.DateInput(attrs={"type": "date"}),
            "payment_processor_reference": forms.TextInput(
                attrs={"placeholder": "Approved processor reference only"}
            ),
        }

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        if patient:
            self.instance.patient = patient
            self.fields["superbill"].queryset = patient.superbills.all()
        self.fields["superbill"].required = False


class AccessUserCreateForm(StyledFormMixin, forms.ModelForm):
    """Administrator-only user provisioning form without elevated Django admin flags."""

    password1 = forms.CharField(
        label="Temporary password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm temporary password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "credential",
            "must_use_mfa",
        ]

    def __init__(self, *args, allow_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        excluded_roles = {User.Role.PATIENT, User.Role.SUPER_ADMIN}
        if not allow_admin:
            excluded_roles.add(User.Role.ADMIN)
        self.fields["role"].choices = [
            choice for choice in User.Role.choices if choice[0] not in excluded_roles
        ]

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
            return cleaned
        if password2:
            prospective_user = User(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
                email=cleaned.get("email", ""),
            )
            validate_password(password2, prospective_user)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class EmployeeOnboardingForm(AccessUserCreateForm):
    """Create a staff account using plain-language, least-privilege roles."""

    least_privilege_confirmed = forms.BooleanField(
        label="I verified that this employee needs this level of access.",
        required=True,
        help_text="Assign the lowest-access role that supports the employee's job duties.",
    )

    field_order = [
        "first_name",
        "last_name",
        "email",
        "username",
        "role",
        "credential",
        "must_use_mfa",
        "least_privilege_confirmed",
        "password1",
        "password2",
    ]

    ROLE_LABELS = {
        User.Role.THERAPIST: "Physical Therapist (PT) — documentation and note signing",
        User.Role.ASSISTANT: "Physical Therapist Assistant (PTA) — assigned clinical work",
        User.Role.SCHEDULER: "Front Desk / Office Admin — scheduling, intake, and demographics",
        User.Role.BILLER: "Billing Specialist — billing and minimum-necessary demographics",
        User.Role.DIRECTOR: "Clinical Director — organization-wide clinical oversight",
        User.Role.COMPLIANCE: "Compliance Officer — authorized audit and clinical review",
        User.Role.ADMIN: "Organization Administrator — account and facility administration",
    }

    def __init__(self, *args, allow_admin=False, **kwargs):
        super().__init__(*args, allow_admin=allow_admin, **kwargs)
        allowed_roles = [
            User.Role.THERAPIST,
            User.Role.ASSISTANT,
            User.Role.SCHEDULER,
            User.Role.BILLER,
            User.Role.DIRECTOR,
            User.Role.COMPLIANCE,
        ]
        if allow_admin:
            allowed_roles.append(User.Role.ADMIN)
        self.fields["role"].choices = [
            (role, self.ROLE_LABELS[role]) for role in allowed_roles
        ]
        self.fields["role"].label = "Employee role / workspace access"
        self.fields["role"].help_text = (
            "Front Desk / Office Admin is non-clinical and cannot manage "
            "accounts or facility settings."
        )
        self.fields["credential"].label = "Professional credential or license"
        self.fields["credential"].help_text = (
            "Required for PT and PTA accounts; leave blank for non-clinical roles."
        )
        self.fields["must_use_mfa"].label = "Require MFA under the organization policy"
        self.fields["must_use_mfa"].help_text = (
            "This records the policy requirement. Connect an approved identity provider "
            "to enforce MFA in production."
        )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("role") in {User.Role.THERAPIST, User.Role.ASSISTANT}
            and not cleaned.get("credential", "").strip()
        ):
            self.add_error(
                "credential",
                "Enter the professional credential or license for a PT or PTA account.",
            )
        return cleaned


class AccessUserUpdateForm(StyledFormMixin, forms.ModelForm):
    """Administrator-only role and account-state updates."""

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "role",
            "credential",
            "must_use_mfa",
            "is_active",
        ]

    def __init__(self, *args, allow_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        excluded_roles = {User.Role.PATIENT, User.Role.SUPER_ADMIN}
        if not allow_admin:
            excluded_roles.add(User.Role.ADMIN)
        self.fields["role"].choices = [
            choice for choice in User.Role.choices if choice[0] not in excluded_roles
        ]


class AccessPasswordResetForm(StyledFormMixin, forms.Form):
    """Reset a credential without putting the password in audit metadata."""

    password1 = forms.CharField(
        label="New temporary password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm new temporary password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._style_fields()

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
            return cleaned
        if password2:
            validate_password(password2, self.user)
        return cleaned


class FacilitySettingsForm(StyledFormMixin, forms.ModelForm):
    """Facility onboarding and white-label workspace settings."""

    class Meta:
        model = Organization
        fields = ["name", "logo", "support_email", "support_phone", "address"]
        labels = {
            "name": "Facility display name",
            "logo": "Facility logo",
            "support_email": "Facility support email",
            "support_phone": "Facility support phone",
            "address": "Facility address",
        }
        widgets = {
            "logo": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
            "address": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "logo": "PNG, JPG, or WebP only; maximum 2 MB. SVG is intentionally not accepted.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if not logo:
            return logo
        if logo.size > 2 * 1024 * 1024:
            raise ValidationError("Logo must be 2 MB or smaller.")
        allowed_content_types = {"image/png", "image/jpeg", "image/webp"}
        content_type = getattr(logo, "content_type", None)
        if content_type and content_type not in allowed_content_types:
            raise ValidationError("Upload a PNG, JPG, or WebP logo.")
        try:
            image = Image.open(logo)
            image.verify()
            if image.width * image.height > 20_000_000:
                raise ValidationError("Logo dimensions are too large.")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValidationError("Uploaded logo is not a valid image.") from exc
        finally:
            logo.seek(0)
        return logo
