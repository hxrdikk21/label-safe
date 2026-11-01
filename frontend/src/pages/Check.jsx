import { useEffect, useMemo, useRef, useState } from 'react';
import { Info } from 'lucide-react';
import EvidenceGraph from '../components/EvidenceGraph';
import InteractionMap from '../components/InteractionMap';
import FindingCard from '../components/FindingCard';
import SearchPicker from '../components/SearchPicker';
import FollowUp from '../components/FollowUp';
import SeverityBadge from '../components/SeverityBadge';
import Sticker from '../components/Sticker';
import { FINDING_TONES, FINDING_TYPES, SEVERITY_ORDER } from '../data/catalog';
import {
  allergyItem,
  conditionItem,
  medicationItem,
  medicationsApi,
  profileApi,
  resolveMedications,
  safetyApi,
  vocabApi,
} from '../services/api';

const title = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());

// The worked example (search hits shape: { concept, has_rules }).
const EXAMPLE = [
  { concept: { rxcui: '11289', canonical_name: 'warfarin', term_type: 'IN', ingredients: [], synonyms: [] }, has_rules: true },
  { concept: { rxcui: '5640', canonical_name: 'ibuprofen', term_type: 'IN', ingredients: [], synonyms: [] }, has_rules: true },
].map(medicationItem);

const STATUS = {
  risk_identified: 'Risks found',
  no_issue_found_in_checked_sources: 'No issue found in the checked sources',
  insufficient_evidence: 'Not enough evidence to decide',
  ambiguous_medication_identity: 'A medication could not be identified',
  conflicting_evidence: 'Sources disagree',
  requires_professional_review: 'Needs professional review',
  check_unavailable: 'Check unavailable',
};

const rank = (s) => {
  const i = SEVERITY_ORDER.indexOf(s);
  return i === -1 ? SEVERITY_ORDER.length : i;
};

export default function Check({ user }) {
  const [meds, setMeds] = useState(EXAMPLE);
  const [foods, setFoods] = useState([]);
  const [conditions, setConditions] = useState([]);
  const [allergies, setAllergies] = useState([]);
  // Label explanations per finding_id, for the latest check only (undefined while loading).
  const [explanations, setExplanations] = useState({ checkId: null, byId: undefined });
  const latestCheck = useRef(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [checkId, setCheckId] = useState(0);
  const [saved, setSaved] = useState(null);
  const [selected, setSelected] = useState(null);
  // Full stored records by lower-case name, so saving keeps their codes, UNIIs and severities.
  const [stored, setStored] = useState({ conditions: {}, allergies: {} });
  const touched = useRef(false);
  const edited = (setter) => (value) => {
    touched.current = true;
    setter(value);
  };

  // Signed-in users start from their saved profile, unless they've already started editing.
  const userId = user?.user_id;
  useEffect(() => {
    if (!userId) return;
    profileApi
      .get()
      .then((p) => {
        setStored({
          conditions: Object.fromEntries(p.conditions.map((c) => [c.condition_name.toLowerCase(), c])),
          allergies: Object.fromEntries(p.allergies.map((a) => [a.substance_name.toLowerCase(), a])),
        });
        if (touched.current) return;
        if (p.conditions.length) setConditions(p.conditions.map(conditionItem));
        if (p.allergies.length) setAllergies(p.allergies.map(allergyItem));
        resolveMedications(p.active_medications).then((found) => {
          if (found.length && !touched.current) setMeds(found);
        });
      })
      .catch(() => {});
  }, [userId]);

  const medications = useMemo(() => meds.map((m) => m.concept), [meds]);
  const nameByRxcui = Object.fromEntries(meds.map((m) => [m.concept.rxcui, title(m.concept.canonical_name)]));
  const profile = {
    active_medications: meds.map((m) => m.concept.canonical_name),
    conditions: conditions.map(
      (c) => stored.conditions[c.label.toLowerCase()] || { condition_name: c.label, icd10_code: c.code || null },
    ),
    allergies: allergies.map(
      (a) => stored.allergies[a.label.toLowerCase()] || { substance_name: a.label, unii: a.unii || null },
    ),
  };
  // Results describe the inputs they were computed for; edits after a check make them stale.
  const foodNames = foods.map((f) => f.value);
  const inputsKey = JSON.stringify([meds, foods, conditions, allergies].map((list) => list.map((x) => x.key)));
  const stale = result !== null && result.inputsKey !== inputsKey;
  const userContext = { user_id: user?.user_id || 'guest', ...profile };

  const run = async (e) => {
    e.preventDefault();
    if (!meds.length) {
      setError('Add at least one medication.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = { medications, food_items: foodNames.length ? foodNames : null, user_context: userContext };
      const report = await safetyApi.analyze(payload);
      const thisCheck = ++latestCheck.current;
      setExplanations({ checkId: thisCheck, byId: undefined });
      if (report.findings.length) {
        // Findings show at once; each card fills in its label explanation when this returns.
        safetyApi
          .explainFindings(payload)
          .then((res) => Object.fromEntries(res.explanations.map((x) => [x.finding_id, x])))
          .catch(() => ({}))
          .then((byId) => latestCheck.current === thisCheck && setExplanations({ checkId: thisCheck, byId }));
      }
      setResult({
        report,
        medications,
        userContext,
        foods: foodNames,
        inputsKey,
        unruled: meds.filter((m) => !m.has_rules),
      });
      setCheckId((n) => n + 1);
      setSelected(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const saveProfile = async () => {
    try {
      // PUT replaces the whole profile: keep the care team and history edited on the Profile page.
      await profileApi.put({ ...(await profileApi.get()), ...profile });
      setSaved('Saved to your profile.');
    } catch (err) {
      setSaved(err.message);
    }
  };

  const report = result?.report;
  const findings = report ? [...report.findings].sort((a, b) => rank(a.severity) - rank(b.severity)) : [];
  const counts = findings.reduce((acc, f) => ({ ...acc, [f.finding_type]: (acc[f.finding_type] || 0) + 1 }), {});

  return (
    <div className="container page check">
      <div className="page-head">
        <h1>Check interactions</h1>
        <p className="muted">
          Add the medications, then anything else that matters. One check covers drug–drug, drug–food, condition and
          allergy risks.
        </p>
      </div>

      <div className="check-grid">
        <form className="sheet form" onSubmit={run}>
          <div className="form-head">
            <span>Your list</span>
            <span>{meds.length} medication{meds.length === 1 ? '' : 's'}</span>
          </div>
          <SearchPicker
            label="Medications"
            hint="Search by generic or brand name."
            placeholder="Start typing, e.g. war"
            values={meds}
            onChange={edited(setMeds)}
            search={medicationsApi.suggest}
          />
          <SearchPicker
            label="Foods & drinks"
            placeholder="e.g. grapefruit"
            values={foods}
            onChange={edited(setFoods)}
            search={vocabApi.foods}
            allowFree
            tone="food"
          />
          <SearchPicker
            label="Conditions"
            hint="Any ICD-10-CM diagnosis."
            placeholder="e.g. asthma"
            values={conditions}
            onChange={edited(setConditions)}
            search={vocabApi.conditions}
            tone="condition"
          />
          <SearchPicker
            label="Allergies"
            hint="An allergy group or a medicine ingredient."
            placeholder="e.g. penicillin"
            values={allergies}
            onChange={edited(setAllergies)}
            search={vocabApi.allergens}
            tone="allergy"
          />

          {error && <p className="error">{error}</p>}
          <div className="form-actions">
            <button className="btn btn-primary" disabled={loading}>
              {loading ? 'Checking…' : 'Check'}
            </button>
            {user && (
              <button type="button" className="btn btn-ghost" onClick={saveProfile}>
                Save to my profile
              </button>
            )}
          </div>
          {saved && <p className="hint">{saved}</p>}
        </form>

        <div className="results" aria-live="polite">
          <InteractionMap
            meds={meds}
            foods={foodNames}
            conditions={conditions.map((c) => ({ name: c.label, icd10: c.code }))}
            allergies={allergies.map((a) => a.label)}
            findings={stale ? undefined : report?.findings}
            selectedId={selected?.finding_id}
            onSelect={(f) => setSelected(selected?.finding_id === f.finding_id ? null : f)}
          />
          {selected && <EvidenceGraph finding={selected} names={nameByRxcui} onClose={() => setSelected(null)} />}

          {!report && (
            <div className="sheet empty">
              <Info size={20} aria-hidden="true" />
              <p className="muted">Press Check to find the risks. Try the example: Warfarin and Ibuprofen.</p>
            </div>
          )}

          {report && (
            <>
              {stale && (
                <p className="hint warning" role="status">
                  You changed the list after this check. Press Check to update these results.
                </p>
              )}
              <section className="sheet summary">
                <div className="summary-top">
                  <p className="summary-title">{STATUS[report.overall_status] || report.overall_status}</p>
                  <SeverityBadge severity={findings.length ? report.highest_severity : 'NONE'} />
                </div>
                <p className="hint">
                  {findings.length} finding{findings.length === 1 ? '' : 's'} across{' '}
                  {report.evaluated_medication_count} medication{report.evaluated_medication_count === 1 ? '' : 's'}
                </p>
                {findings.length > 0 && (
                  <div className="chips">
                    {Object.entries(counts).map(([type, n]) => (
                      <Sticker key={type} tone={FINDING_TONES[type] || 'ddi'}>
                        {FINDING_TYPES[type] || type}: {n}
                      </Sticker>
                    ))}
                  </div>
                )}
              </section>

              {result.unruled.length > 0 && (
                <p className="hint warning">
                  RxGuard has no rules yet for {result.unruled.map((m) => title(m.concept.canonical_name)).join(', ')}
                  {result.unruled.length === 1
                    ? ', so it was not checked. No finding for it does not mean it is safe.'
                    : ', so they were not checked. No finding for them does not mean they are safe.'}
                </p>
              )}
              {findings.length === 0 && (
                <p className="sheet empty">
                  Nothing was flagged in the sources RxGuard checks. That does not mean the combination is safe.
                </p>
              )}
              {findings.map((f) => (
                <FindingCard
                  key={f.finding_id}
                  finding={f}
                  names={nameByRxcui}
                  selected={selected?.finding_id === f.finding_id}
                  onShowEvidence={() => setSelected(f)}
                  explanation={explanations.byId === undefined ? undefined : explanations.byId[f.finding_id] || null}
                />
              ))}

              {report.missing_data_warnings.map((w) => (
                <p key={w} className="hint warning">
                  {w}
                </p>
              ))}

              <FollowUp
                key={checkId}
                medications={result.medications}
                foods={result.foods}
                userContext={result.userContext}
              />

              <p className="hint">{report.disclaimer}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
