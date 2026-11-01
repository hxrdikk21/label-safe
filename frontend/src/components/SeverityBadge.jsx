const LABELS = {
  CONTRAINDICATED: 'Contraindicated',
  MAJOR: 'Major',
  MODERATE: 'Moderate',
  MINOR: 'Minor',
  PRECAUTION: 'Precaution',
  UNKNOWN_SEVERITY: 'Unknown severity',
  NONE: 'Nothing found',
};

export default function SeverityBadge({ severity }) {
  return <span className={`sev sev-${severity}`}>{LABELS[severity] || severity}</span>;
}
