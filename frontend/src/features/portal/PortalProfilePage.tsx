import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalProfile } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export function PortalProfilePage() {
  const [profile, setProfile] = useState<PortalProfile | null>(null);
  const [error, setError] = useState("");

  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  const [emergencyContact, setEmergencyContact] = useState("");
  const [contactError, setContactError] = useState("");
  const [contactNotice, setContactNotice] = useState("");
  const [submittingContact, setSubmittingContact] = useState(false);

  const [pharmacyName, setPharmacyName] = useState("");
  const [pharmacyPhone, setPharmacyPhone] = useState("");
  const [pharmacyAddress, setPharmacyAddress] = useState("");
  const [preferredContactMethod, setPreferredContactMethod] = useState("email");
  const [emailNotificationsEnabled, setEmailNotificationsEnabled] = useState(true);
  const [smsNotificationsEnabled, setSmsNotificationsEnabled] = useState(false);
  const [prefsError, setPrefsError] = useState("");
  const [prefsNotice, setPrefsNotice] = useState("");
  const [savingPrefs, setSavingPrefs] = useState(false);

  async function load() {
    try {
      const result = await api.portalProfile();
      setProfile(result.profile);
      setPhone(result.profile.phone);
      setEmail(result.profile.email);
      setAddress(result.profile.address);
      setEmergencyContact(result.profile.emergencyContact);
      setPharmacyName(result.profile.pharmacyName);
      setPharmacyPhone(result.profile.pharmacyPhone);
      setPharmacyAddress(result.profile.pharmacyAddress);
      setPreferredContactMethod(result.profile.preferredContactMethod);
      setEmailNotificationsEnabled(result.profile.emailNotificationsEnabled);
      setSmsNotificationsEnabled(result.profile.smsNotificationsEnabled);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your profile."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function submitContactChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setContactError("");
    setContactNotice("");
    setSubmittingContact(true);
    try {
      await api.portalSubmitProfileChangeRequest({ phone, email, address, emergencyContact });
      setContactNotice("Your changes were submitted for staff review. They'll take effect once approved.");
      await load();
    } catch (requestError) {
      setContactError(requestMessage(requestError, "Unable to submit this change."));
    } finally {
      setSubmittingContact(false);
    }
  }

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPrefsError("");
    setPrefsNotice("");
    setSavingPrefs(true);
    try {
      await api.portalUpdateProfilePreferences({
        pharmacyName,
        pharmacyPhone,
        pharmacyAddress,
        preferredContactMethod,
        emailNotificationsEnabled,
        smsNotificationsEnabled,
      });
      setPrefsNotice("Saved.");
      await load();
    } catch (requestError) {
      setPrefsError(requestMessage(requestError, "Unable to save your preferences."));
    } finally {
      setSavingPrefs(false);
    }
  }

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!profile) return <p className="portal-empty">Loading your profile...</p>;

  const hasPendingRequest = Boolean(profile.pendingChangeRequest);

  return (
    <>
      <h1>My Profile</h1>

      <div className="portal-card">
        <p className="eyebrow">{profile.fullName}</p>
        <p className="portal-empty">Date of birth: {formatDate(profile.dateOfBirth)}</p>
      </div>

      <div className="portal-card">
        <h3>Contact information</h3>
        <p className="portal-empty">
          Changes to these fields are reviewed by our clinic staff before taking effect, to protect your account.
        </p>
        {hasPendingRequest && profile.pendingChangeRequest && (
          <p className="form-notice" role="status">
            A change request submitted {formatDate(profile.pendingChangeRequest.createdAt)} is pending staff review.
          </p>
        )}
        <form onSubmit={submitContactChange} style={{ display: "grid", gap: ".6rem" }}>
          <label>
            <span>Phone</span>
            <input value={phone} onChange={(event) => setPhone(event.target.value)} disabled={hasPendingRequest} />
          </label>
          <label>
            <span>Email</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={hasPendingRequest} />
          </label>
          <label>
            <span>Address</span>
            <textarea rows={2} value={address} onChange={(event) => setAddress(event.target.value)} disabled={hasPendingRequest} />
          </label>
          <label>
            <span>Emergency contact</span>
            <input
              value={emergencyContact}
              onChange={(event) => setEmergencyContact(event.target.value)}
              placeholder="Name and phone number"
              disabled={hasPendingRequest}
            />
          </label>
          {contactError && <p className="form-error" role="alert">{contactError}</p>}
          {contactNotice && <p className="form-notice" role="status">{contactNotice}</p>}
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={submittingContact || hasPendingRequest}>
              {submittingContact ? "Submitting..." : "Submit changes for review"}
            </button>
          </div>
        </form>
      </div>

      <div className="portal-card">
        <h3>Pharmacy</h3>
        <form onSubmit={savePreferences} style={{ display: "grid", gap: ".6rem" }}>
          <label>
            <span>Pharmacy name</span>
            <input value={pharmacyName} onChange={(event) => setPharmacyName(event.target.value)} />
          </label>
          <label>
            <span>Pharmacy phone</span>
            <input value={pharmacyPhone} onChange={(event) => setPharmacyPhone(event.target.value)} />
          </label>
          <label>
            <span>Pharmacy address</span>
            <textarea rows={2} value={pharmacyAddress} onChange={(event) => setPharmacyAddress(event.target.value)} />
          </label>

          <h3 style={{ marginTop: ".5rem" }}>Communication preferences</h3>
          <label>
            <span>Preferred contact method</span>
            <select value={preferredContactMethod} onChange={(event) => setPreferredContactMethod(event.target.value)}>
              <option value="email">Email</option>
              <option value="phone">Phone call</option>
              <option value="sms">Text message</option>
            </select>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
            <input
              type="checkbox"
              checked={emailNotificationsEnabled}
              onChange={(event) => setEmailNotificationsEnabled(event.target.checked)}
              style={{ width: "auto" }}
            />
            Email me when I receive a new secure message
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
            <input
              type="checkbox"
              checked={smsNotificationsEnabled}
              onChange={(event) => setSmsNotificationsEnabled(event.target.checked)}
              style={{ width: "auto" }}
            />
            Text me updates about my in-home PT visits (request received, therapist matched, visit reminders, provider on the way)
          </label>

          {prefsError && <p className="form-error" role="alert">{prefsError}</p>}
          {prefsNotice && <p className="form-notice" role="status">{prefsNotice}</p>}
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={savingPrefs}>
              {savingPrefs ? "Saving..." : "Save preferences"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
