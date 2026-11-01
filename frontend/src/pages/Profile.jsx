import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import RecordList from '../components/RecordList';
import SearchPicker from '../components/SearchPicker';
import {
  allergyItem,
  conditionItem,
  medicationsApi,
  profileApi,
  resolveMedications,
  vocabApi,
} from '../services/api';

const HOSPITAL_FIELDS = [
  { name: 'name', label: 'Hospital or clinic', required: true },
  { name: 'department', label: 'Department' },
  { name: 'address', label: 'Address' },
  { name: 'phone', label: 'Phone' },
];
const DOCTOR_FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'specialty', label: 'Specialty' },
  { name: 'hospital_affiliation', label: 'Hospital' },
  { name: 'contact_phone', label: 'Phone' },
];
const VISIT_FIELDS = [
  { name: 'visit_date', label: 'Date', type: 'date', required: true },
  { name: 'reason_for_visit', label: 'Reason', required: true },
  { name: 'hospital_name', label: 'Hospital or clinic', required: true },
  { name: 'doctor_name', label: 'Doctor', required: true },
  { name: 'clinical_notes', label: 'Notes', type: 'textarea' },
];
const PRESCRIPTION_FIELDS = [
  { name: 'medication_name', label: 'Medicine', required: true },
  { name: 'dosage', label: 'Dose, e.g. 500 mg twice a day' },
  { name: 'prescribed_by', label: 'Prescribed by', required: true },
  { name: 'prescribed_date', label: 'Date', type: 'date', required: true },
  { name: 'status', label: 'Status', options: ['ACTIVE', 'COMPLETED', 'DISCONTINUED'], required: true },
  { name: 'instructions', label: 'Instructions', type: 'textarea' },
];
const join = (...parts) => parts.filter(Boolean).join(' · ') || undefined;

export default function Profile({ user }) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  // Stored condition/allergy records by name, so saving keeps fields the search boxes don't show.
  const [stored, setStored] = useState({ conditions: {}, allergies: {} });
  const [meds, setMeds] = useState([]);
  const [conditions, setConditions] = useState([]);
  const [allergies, setAllergies] = useState([]);
  const [hospitals, setHospitals] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [visits, setVisits] = useState([]);
  const [prescriptions, setPrescriptions] = useState([]);

  const edit = (setter) => (value) => {
    setDirty(true);
    setStatus(null);
    setter(value);
  };

  const userId = user?.user_id;
  useEffect(() => {
    if (!userId) return;
    profileApi
      .get()
      .then(async (p) => {
        setStored({
          conditions: Object.fromEntries(p.conditions.map((c) => [c.condition_name.toLowerCase(), c])),
          allergies: Object.fromEntries(p.allergies.map((a) => [a.substance_name.toLowerCase(), a])),
        });
        setConditions(p.conditions.map(conditionItem));
        setAllergies(p.allergies.map(allergyItem));
        setHospitals(p.hospitals);
        setDoctors(p.doctors);
        setVisits(p.medical_visits);
        setPrescriptions(p.prescriptions);
        setMeds(await resolveMedications(p.active_medications));
        setLoaded(true);
      })
      .catch((err) => setError(err.message));
  }, [userId]);

  if (!user) {
    return (
      <div className="container page">
        <div className="page-head">
          <h1>Your profile</h1>
          <p className="muted">
            Sign in to keep your medicines, conditions, allergies, care team and history in one place. Every check
            starts from them.
          </p>
          <a className="btn btn-primary" href="#/signin">
            Sign in
          </a>
        </div>
      </div>
    );
  }

  const save = async () => {
    setSaving(true);
    setStatus(null);
    try {
      await profileApi.put({
        active_medications: meds.map((m) => m.concept.canonical_name),
        conditions: conditions.map(
          (c) => stored.conditions[c.label.toLowerCase()] || { condition_name: c.label, icd10_code: c.code || null },
        ),
        allergies: allergies.map(
          (a) => stored.allergies[a.label.toLowerCase()] || { substance_name: a.label, unii: a.unii || null },
        ),
        hospitals,
        doctors,
        medical_visits: visits,
        prescriptions,
      });
      setDirty(false);
      setStatus('Profile saved.');
    } catch (err) {
      setStatus(err.message);
    } finally {
      setSaving(false);
    }
  };

  const wipe = async () => {
    if (!window.confirm('Delete all health details saved in your profile? Your account stays.')) return;
    try {
      await profileApi.remove();
      [setMeds, setConditions, setAllergies, setHospitals, setDoctors, setVisits, setPrescriptions].forEach((set) =>
        set([]),
      );
      setDirty(false);
      setStatus('Your health details were deleted.');
    } catch (err) {
      setStatus(err.message);
    }
  };

  return (
    <div className="container page profile">
      <div className="page-head">
        <h1>Your profile</h1>
        <p className="muted">Checks you run while signed in start from what you save here.</p>
      </div>

      <section className="sheet account" aria-label="Account">
        <dl>
          <div>
            <dt>Name</dt>
            <dd>{user.full_name || '—'}</dd>
          </div>
          <div>
            <dt>Username</dt>
            <dd>{user.username}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user.email || '—'}</dd>
          </div>
          <div>
            <dt>Two-step sign-in</dt>
            <dd>{user.totp_enabled ? 'On' : 'Off'}</dd>
          </div>
        </dl>
      </section>

      {error && <p className="error">{error}</p>}
      {!loaded && !error && <p className="hint">Loading your profile…</p>}

      {loaded && (
        <>
          <section className="sheet form" aria-labelledby="health-title">
            <div className="form-head">
              <span id="health-title">Health details</span>
              <span>Used by every check</span>
            </div>
            <SearchPicker
              label="Medicines you take"
              placeholder="Start typing, e.g. war"
              values={meds}
              onChange={edit(setMeds)}
              search={medicationsApi.suggest}
            />
            <SearchPicker
              label="Conditions"
              hint="Any ICD-10-CM diagnosis."
              placeholder="e.g. asthma"
              values={conditions}
              onChange={edit(setConditions)}
              search={vocabApi.conditions}
              tone="condition"
            />
            <SearchPicker
              label="Allergies"
              hint="An allergy group or a medicine ingredient."
              placeholder="e.g. penicillin"
              values={allergies}
              onChange={edit(setAllergies)}
              search={vocabApi.allergens}
              tone="allergy"
            />
          </section>

          <div className="records-grid">
            <RecordList
              title="Hospitals and clinics"
              addLabel="Add hospital"
              fields={HOSPITAL_FIELDS}
              values={hospitals}
              onChange={edit(setHospitals)}
              summary={(h) => ({ title: h.name, detail: join(h.department, h.phone) })}
            />
            <RecordList
              title="Doctors"
              addLabel="Add doctor"
              fields={DOCTOR_FIELDS}
              values={doctors}
              onChange={edit(setDoctors)}
              summary={(d) => ({ title: d.name, detail: join(d.specialty, d.hospital_affiliation) })}
            />
            <RecordList
              title="Visits"
              addLabel="Add visit"
              fields={VISIT_FIELDS}
              values={visits}
              onChange={edit(setVisits)}
              summary={(v) => ({ title: v.reason_for_visit, detail: join(v.visit_date, v.doctor_name, v.hospital_name) })}
            />
            <RecordList
              title="Prescriptions"
              addLabel="Add prescription"
              fields={PRESCRIPTION_FIELDS}
              values={prescriptions}
              onChange={edit(setPrescriptions)}
              summary={(p) => ({
                title: join(p.medication_name, p.dosage),
                detail: join(p.status.toLowerCase(), p.prescribed_by, p.prescribed_date),
              })}
            />
          </div>

          <div className="sheet save-bar" role="region" aria-label="Save profile">
            <span className="hint" role="status">
              {status || (dirty ? 'You have unsaved changes.' : 'All changes saved.')}
            </span>
            <div className="form-actions">
              <button type="button" className="btn btn-ghost" onClick={wipe}>
                <Trash2 size={16} aria-hidden="true" /> Delete health details
              </button>
              <button type="button" className="btn btn-primary" disabled={saving || !dirty} onClick={save}>
                {saving ? 'Saving…' : 'Save profile'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
