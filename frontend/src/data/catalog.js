// Medications, foods, conditions and allergens are searched through the API
// (GET /medications/search and /vocab/{kind}/search).

export const FINDING_TYPES = {
  DRUG_DRUG_INTERACTION: 'Drug–drug',
  DRUG_FOOD_INTERACTION: 'Drug–food',
  CONTRAINDICATION: 'Condition',
  ALLERGY_EXCIPIENT: 'Allergy',
};

// Sticker colour per interaction type (see .tone-* in styles.css).
export const FINDING_TONES = {
  DRUG_DRUG_INTERACTION: 'ddi',
  DRUG_FOOD_INTERACTION: 'food',
  CONTRAINDICATION: 'condition',
  ALLERGY_EXCIPIENT: 'allergy',
};

export const SEVERITY_ORDER = ['CONTRAINDICATED', 'MAJOR', 'MODERATE', 'MINOR', 'PRECAUTION', 'UNKNOWN_SEVERITY'];
