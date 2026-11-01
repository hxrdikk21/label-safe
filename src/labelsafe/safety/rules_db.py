"""
Safety rules repository.
In-memory and seed storage layer providing rapid, indexed symbolic rule lookup.
"""

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from src.labelsafe.core.config import get_settings
from src.labelsafe.safety.models import AllergyRule, DCIRule, DDIRule, DFIRule, RuleStatus

logger = logging.getLogger(__name__)

SafetyRule = DDIRule | DFIRule | DCIRule | AllergyRule
# Output of `make rules`; tests point this elsewhere so results never depend on a local build.
GENERATED_RULES_DIR = Path(
    os.environ.get("LABELSAFE_GENERATED_RULES_DIR")
    or Path(__file__).resolve().parents[3] / "data" / "generated"
)

# Words too generic to identify a condition on their own ("disease" would match every rule).
_GENERIC_CONDITION_WORDS = frozenset(
    {"disease", "diseases", "disorder", "disorders", "severe", "chronic", "and", "with"}
)


def _words(text: str) -> list[str]:
    """Lowercase words with a trailing plural 's' removed ('seizures' -> 'seizure')."""
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text.lower())]


def mentions(text: str, term: str) -> bool:
    """Whole-word match of `term` in `text`, ignoring negated forms like 'non-dairy' or 'alcohol-free'."""
    pattern = rf"(?<![\w-]){re.escape(term.lower())}(?![\w]|-free)"
    return re.search(pattern, text.lower()) is not None


class SafetyRulesRepository:
    """Indexed clinical rules repository for deterministic safety screening."""

    def __init__(self) -> None:
        # Indexed storage for O(1) pairwise DDI lookup: tuple(sorted([rxcui_a, rxcui_b])) -> DDIRule
        self._ddi_index: dict[tuple[str, str], DDIRule] = {}

        # Indexed storage for DFI: tuple(rxcui, food_identifier_lower) -> DFIRule
        self._dfi_index: dict[tuple[str, str], DFIRule] = {}

        # Indexed storage for DCI: tuple(rxcui, condition_code_upper) -> DCIRule
        self._dci_index: dict[tuple[str, str], DCIRule] = {}

        # Indexed storage for Allergies: list of AllergyRules
        self._allergy_rules: list[AllergyRule] = []

        # Every rule by rule_id, for Evidence Navigator lookups.
        self._rules_by_id: dict[str, SafetyRule] = {}

    def clear(self) -> None:
        """Clears all in-memory indexes."""
        self._ddi_index.clear()
        self._dfi_index.clear()
        self._dci_index.clear()
        self._allergy_rules.clear()
        self._rules_by_id.clear()

    @staticmethod
    def _normalize_pair(rxcui_a: str, rxcui_b: str) -> tuple[str, str]:
        """Returns sorted tuple for symmetric order-independent pairwise matching."""
        a, b = str(rxcui_a).strip(), str(rxcui_b).strip()
        return (a, b) if a <= b else (b, a)

    def add_ddi_rule(self, rule: DDIRule, replace: bool = True) -> None:
        """Adds a DDI rule into the indexed repository."""
        key = self._normalize_pair(rule.subject_rxcui, rule.interacting_rxcui)
        if not replace and key in self._ddi_index:
            return
        self._ddi_index[key] = rule
        self._rules_by_id[rule.rule_id] = rule

    def add_dfi_rule(self, rule: DFIRule, replace: bool = True) -> None:
        """Adds a Drug-Food interaction rule into the indexed repository."""
        key = (str(rule.subject_rxcui).strip(), rule.food_identifier.lower().strip())
        if not replace and key in self._dfi_index:
            return
        self._dfi_index[key] = rule
        self._rules_by_id[rule.rule_id] = rule

    def add_dci_rule(self, rule: DCIRule) -> None:
        """Adds a Drug-Condition contraindication rule into the indexed repository."""
        for code in (rule.condition_code, *rule.additional_codes):
            self._dci_index[(str(rule.subject_rxcui).strip(), code.upper().strip())] = rule
        self._rules_by_id[rule.rule_id] = rule

    def add_allergy_rule(self, rule: AllergyRule) -> None:
        """Adds an allergy/excipient cross-reactivity rule."""
        self._allergy_rules.append(rule)
        self._rules_by_id[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> SafetyRule | None:
        """Returns any rule (DDI, DFI, DCI or allergy) by its rule_id."""
        return self._rules_by_id.get(rule_id)

    def find_ddi(self, rxcui_a: str, rxcui_b: str) -> DDIRule | None:
        """Finds a verified DDI rule between two medication RxCUIs (order-independent)."""
        key = self._normalize_pair(rxcui_a, rxcui_b)
        rule = self._ddi_index.get(key)
        if rule and rule.status == RuleStatus.ACTIVE:
            return rule
        return None

    def find_dfi(self, rxcui: str, food_query: str) -> DFIRule | None:
        """
        Finds a DFI rule whose food (or one of its aliases) is named as a whole word in the query,
        e.g. 'fresh grapefruit juice' -> grapefruit, 'milk' -> dairy; 'non-dairy creamer' matches nothing.
        """
        clean_rxcui = str(rxcui).strip()
        for (idx_rxcui, food_id), rule in self._dfi_index.items():
            if idx_rxcui != clean_rxcui or rule.status != RuleStatus.ACTIVE:
                continue
            if any(mentions(food_query, term) for term in (food_id, *rule.food_aliases)):
                return rule
        return None

    def find_dci(self, rxcui: str, condition_code: str) -> DCIRule | None:
        """
        Finds a contraindication rule for a drug and ICD-10 code. A more specific patient code matches
        a broader rule code (patient 'N18.41' matches rule 'N18.4'), never the reverse ('J' matches nothing).
        """
        clean_rxcui = str(rxcui).strip()
        clean_code = condition_code.upper().strip()
        for (idx_rxcui, idx_code), r in self._dci_index.items():
            if idx_rxcui == clean_rxcui and r.status == RuleStatus.ACTIVE and clean_code.startswith(idx_code):
                return r
        return None

    def find_dci_by_name(self, rxcui: str, condition_name: str) -> DCIRule | None:
        """
        Fallback when the patient's condition has no code: every specific word of the name must appear
        in the rule's condition name ('asthma' -> 'Asthma and Bronchospasm'; 'disease' alone matches nothing).
        """
        words = [w for w in _words(condition_name) if w not in _GENERIC_CONDITION_WORDS]
        if not words:
            return None
        clean_rxcui = str(rxcui).strip()
        for (idx_rxcui, _code), r in self._dci_index.items():
            if idx_rxcui == clean_rxcui and r.status == RuleStatus.ACTIVE:
                display = set(_words(r.condition_display))
                if all(w in display for w in words):
                    return r
        return None

    def find_allergy_match(
        self,
        reported_allergen: str,
        target_rxcui: str | None = None,
        target_uniis: list[str] | None = None,
        allergen_unii: str | None = None,
    ) -> AllergyRule | None:
        """
        Matches a patient's reported allergen against active moieties or inactive excipients.
        Performs robust keyword and token root matching (e.g. 'Penicillin Allergy' matches 'Penicillins').
        `allergen_unii` identifies the allergen itself; `target_uniis` are the drug's ingredients.
        """
        clean_allergen = reported_allergen.lower().strip()
        allergen_words = [w.strip() for w in clean_allergen.replace("-", " ").split() if len(w.strip()) > 3]
        target_uniis_set: set[str] = {u.strip().upper() for u in (target_uniis or [])}
        clean_rxcui = str(target_rxcui).strip() if target_rxcui else None

        for rule in self._allergy_rules:
            if rule.status != RuleStatus.ACTIVE:
                continue

            rule_name_lower = rule.allergen_name.lower()
            rule_group_lower = rule.allergen_group_id.lower()

            # Direct substring match
            allergen_matches = (
                rule_name_lower in clean_allergen
                or clean_allergen in rule_name_lower
                or rule_group_lower in clean_allergen
            )

            if allergen_unii and allergen_unii.strip().upper() in {
                u.upper() for u in rule.cross_reactive_uniis
            }:
                allergen_matches = True

            # Token-level root match (e.g. 'penicillin' matches 'penicillins')
            if not allergen_matches:
                for w in allergen_words:
                    if w in rule_name_lower or w in rule_group_lower:
                        allergen_matches = True
                        break
                    # Strip trailing 's' if plural
                    root = w[:-1] if w.endswith("s") else w
                    if root in rule_name_lower:
                        allergen_matches = True
                        break

            if allergen_matches:
                # Check if target drug RxCUI matches cross-reactive RxCUIs
                if clean_rxcui and clean_rxcui in rule.cross_reactive_rxcuis:
                    return rule

                # Check if any target substance UNII matches cross-reactive UNIIs
                for unii in rule.cross_reactive_uniis:
                    if unii.upper() in target_uniis_set:
                        return rule

        return None

    def load_from_json(self, file_path: str | Path | None = None, replace: bool = True) -> int:
        """
        Loads rules from a seed JSON file into the repository.
        Returns total number of rules loaded.
        """
        if file_path is None:
            # Default to data/seed/safety_rules.json relative to project root
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            seed_file = base_dir / "data" / "seed" / "safety_rules.json"
        else:
            seed_file = Path(file_path)

        if not seed_file.exists():
            logger.warning("Seed safety rules file not found at %s", seed_file)
            return 0

        with open(seed_file, encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for ddi in data.get("ddi_rules", []):
            self.add_ddi_rule(DDIRule(**ddi), replace=replace)
            count += 1

        for dfi in data.get("dfi_rules", []):
            self.add_dfi_rule(DFIRule(**dfi), replace=replace)
            count += 1

        for dci in data.get("dci_rules", []):
            self.add_dci_rule(DCIRule(**dci))
            count += 1

        for allergy in data.get("allergy_rules", []):
            self.add_allergy_rule(AllergyRule(**allergy))
            count += 1

        logger.info("Loaded %d safety rules from %s", count, seed_file)
        return count

    def all_rules(self) -> list[SafetyRule]:
        """Every distinct active rule (DCI rules indexed under several codes appear once)."""
        seen: dict[str, SafetyRule] = {}
        rules: list[SafetyRule] = [
            *self._ddi_index.values(),
            *self._dfi_index.values(),
            *self._dci_index.values(),
            *self._allergy_rules,
        ]
        for rule in rules:
            if rule.status == RuleStatus.ACTIVE:
                seen.setdefault(rule.rule_id, rule)
        return list(seen.values())

    def rule_drugs(self) -> dict[str, str | None]:
        """RxCUI -> display name for every drug a rule covers (None if only an allergy rule lists it)."""
        drugs: dict[str, str | None] = {}
        for ddi in self._ddi_index.values():
            drugs[ddi.subject_rxcui] = drugs.get(ddi.subject_rxcui) or ddi.subject_name
            drugs[ddi.interacting_rxcui] = drugs.get(ddi.interacting_rxcui) or ddi.interacting_name
        for dfi in self._dfi_index.values():
            drugs[dfi.subject_rxcui] = drugs.get(dfi.subject_rxcui) or dfi.subject_name
        for dci in self._dci_index.values():
            drugs[dci.subject_rxcui] = drugs.get(dci.subject_rxcui) or dci.subject_name
        for allergy in self._allergy_rules:
            for rxcui in allergy.cross_reactive_rxcuis:
                drugs.setdefault(rxcui, None)
        return drugs

    def stats(self) -> dict[str, int]:
        """Returns statistics on active indexed rules."""
        return {
            "ddi_count": len(self._ddi_index),
            "dfi_count": len(self._dfi_index),
            "dci_count": len(self._dci_index),
            "allergy_count": len(self._allergy_rules),
            "total_rules": (
                len(self._ddi_index) + len(self._dfi_index) + len(self._dci_index) + len(self._allergy_rules)
            ),
        }


@lru_cache
def get_safety_rules_repo() -> SafetyRulesRepository:
    """Singleton provider initialized with default seed safety rules."""
    repo = SafetyRulesRepository()
    if repo.load_from_json() == 0:
        # An empty rulebook would report every combination as "no issue found".
        raise RuntimeError("No safety rules loaded; refusing to screen without a rulebook")
    # Generated rules (make rules) never override curated ones; files load in name order,
    # so ddinter_rules.json takes precedence over fda_label_rules.json for the same pair.
    include_ddinter = get_settings().include_ddinter  # CC BY-NC-SA: off for commercial deployments
    for generated in sorted(GENERATED_RULES_DIR.glob("*.json")):
        if generated.name.startswith("ddinter") and not include_ddinter:
            continue
        repo.load_from_json(generated, replace=False)
    return repo
