"""
Context provider implementations — one class per section.
"""

import json
import logging
from .base import (
    ContextProvider, HoneyContext,
    NUM_PATTERN, parse_domains_json, extract_domain, safe_conf
)

log = logging.getLogger("singularity")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MISSION HEADER
# ═══════════════════════════════════════════════════════════════════════════════

class MissionHeaderProvider(ContextProvider):
    section_name = "mission_header"

    def render(self, ctx: HoneyContext) -> list[str]:
        m = ctx.mission
        return [
            f"TEMAT MISJI: {m.get('topic', '?')}",
            f"STATYSTYKI: {m.get('sources_found', 0)} znalezionych źródeł | "
            f"{m.get('sources_harvested', 0)} zebranych | "
            f"{m.get('total_words', 0)} słów | "
            f"{m.get('total_entities', 0)} encji | "
            f"{m.get('total_facts', 0)} faktów",
            "",
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. NUMERIC FACT DIGEST
# ═══════════════════════════════════════════════════════════════════════════════

class NumericDigestProvider(ContextProvider):
    section_name = "numeric_digest"

    def render(self, ctx: HoneyContext) -> list[str]:
        raw_claims = ctx.honey.get("raw_claims", [])
        if not raw_claims:
            return []

        digest = []
        for rc in raw_claims[:300]:
            if len(rc) < 5:
                continue
            claim_text = str(rc[0] or "")
            try:
                conf_f = float(rc[4])
            except Exception:
                conf_f = 0.5
            if conf_f < 0.65:
                continue
            for v, u in NUM_PATTERN.findall(claim_text)[:2]:
                entry = f"[{conf_f:.2f}] {v.strip()} {u} — {claim_text[:120]}"
                if entry not in digest:
                    digest.append(entry)
            if len(digest) >= 25:
                break

        if not digest:
            return []
        return (
            ["=== LICZBY KLUCZOWE — DIGEST (do cytowania w raporcie) ==="]
            + digest
            + [""]
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. KEY INTELLIGENCE CLAIMS (top 40)
# ═══════════════════════════════════════════════════════════════════════════════

class KeyClaimsProvider(ContextProvider):
    section_name = "key_claims"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== KLUCZOWE USTALENIA WYWIADOWCZE (hive_claims — top 40) ==="]
        raw_claims = ctx.honey.get("raw_claims")

        if not raw_claims:
            lines.append("Brak twierdzeń wywiadowczych — pipeline extraction nie zebrał claims.")
            lines.append("")
            return lines

        seen = set()
        added = 0
        for row in raw_claims:
            if len(row) == 5:
                claim, evidence, src_url, claim_type, conf = row
            elif len(row) == 3:
                claim, src_url, conf = row
                evidence, claim_type = "", "intelligence"
            else:
                continue

            dedup_key = (claim or "")[:100].lower().strip()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            domain = extract_domain(src_url)
            evidence_snippet = (evidence or "")[:80]
            lines.append(
                f"[{safe_conf(conf)}] [{claim_type or '?'}] {(claim or '')[:200]}"
                + (f" | evid: {evidence_snippet}" if evidence_snippet else "")
                + (f" | src: {domain}" if domain else "")
            )
            added += 1
            if added >= 40:
                break

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CONFIRMED NUMERIC FACTS
# ═══════════════════════════════════════════════════════════════════════════════

class ConfirmedFactsProvider(ContextProvider):
    section_name = "confirmed_facts"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== POTWIERDZONE FAKTY NUMERYCZNE ==="]
        confirmed = ctx.honey.get("confirmed_facts")

        if confirmed:
            for row in confirmed:
                val, unit, ctx_text, src_count, sources_json, domains_json, conf = row
                domains = parse_domains_json(domains_json)
                domain_str = ", ".join(domains[:3]) if domains else "—"
                val_str = f"{val:g}" if val is not None else "?"
                unit_str = f" {unit}" if unit else ""
                lines.append(
                    f"[{conf}] {val_str}{unit_str} — {ctx_text} "
                    f"(źródła: {domain_str}, n={src_count})"
                )
        else:
            # Fallback: extract numbers from high-confidence claims
            lines.append("⚠️  hive_facts pusta — ekstrakcja wartości numerycznych z hive_claims:")
            num_added = 0
            for rc in ctx.honey.get("raw_claims", [])[:200]:
                if len(rc) < 5:
                    continue
                claim_text = str(rc[0] or "")
                src_url = str(rc[2] or "")
                try:
                    conf_f = float(rc[4])
                except Exception:
                    conf_f = 0.5
                if conf_f < 0.6:
                    continue
                matches = NUM_PATTERN.findall(claim_text)
                if matches:
                    domain = extract_domain(src_url)
                    for val_str, unit_str in matches[:2]:
                        lines.append(
                            f"[{conf_f:.2f}] {val_str.strip()} {unit_str} "
                            f"— {claim_text[:150]} ({domain})"
                        )
                        num_added += 1
                        if num_added >= 30:
                            break
                if num_added >= 30:
                    break
            if num_added == 0:
                lines.append("Brak wartości numerycznych w claims dla tej misji.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ALL NUMERIC FACTS (TOP 50)
# ═══════════════════════════════════════════════════════════════════════════════

class AllFactsProvider(ContextProvider):
    section_name = "all_facts"

    def applies(self, ctx: HoneyContext) -> bool:
        return bool(ctx.honey.get("all_facts"))

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== WSZYSTKIE FAKTY NUMERYCZNE (TOP 50) ==="]
        for row in ctx.honey["all_facts"]:
            val, unit, ctx_text, src_count, sources_json, domains_json, conf = row
            domains = parse_domains_json(domains_json)
            domain_str = ", ".join(domains[:2]) if domains else "—"
            val_str = f"{val:g}" if val is not None else "?"
            unit_str = f" {unit}" if unit else ""
            lines.append(f"[{conf}] {val_str}{unit_str} — {ctx_text} ({domain_str})")
        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 6. KEY ENTITIES
# ═══════════════════════════════════════════════════════════════════════════════

class EntitiesProvider(ContextProvider):
    section_name = "entities"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== KLUCZOWE ENCJE ==="]
        top_entities = ctx.honey.get("top_entities")

        if top_entities:
            by_type: dict = {}
            for row in top_entities:
                text, etype, canonical, conf, src_count, context = row
                display = canonical or text
                by_type.setdefault(etype, []).append(f"{display}:{src_count}")
            for etype, items in by_type.items():
                lines.append(f"{etype}: " + " | ".join(items))
        else:
            lines.append("Brak encji.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TOPIC CLUSTERS
# ═══════════════════════════════════════════════════════════════════════════════

class ClustersProvider(ContextProvider):
    section_name = "clusters"

    def render(self, ctx: HoneyContext) -> list[str]:
        # Prefer pre-built cluster context block (includes cross-mission atlas)
        ccb = ctx.honey.get("cluster_context_block")
        if ccb:
            return [ccb, ""]

        lines = ["=== KLASTRY TEMATYCZNE ==="]
        clusters = ctx.honey.get("clusters")

        if clusters:
            for i, row in enumerate(clusters, 1):
                cid, label, kw_json, doc_count, repr_text = row
                kws = []
                if isinstance(kw_json, list):
                    kws = kw_json
                elif isinstance(kw_json, str) and kw_json:
                    try:
                        kws = json.loads(kw_json)
                    except (json.JSONDecodeError, ValueError):
                        pass
                kw_str = ", ".join(kws[:6]) if kws else "—"
                lines.append(f"{i}. {label} ({doc_count} dokumentów): {kw_str}")
        else:
            lines.append("Brak klastrów tematycznych — dokumenty nie były klastrowane.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 8. FALSIFICATION EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════════

class FalsificationProvider(ContextProvider):
    section_name = "falsification"

    def render(self, ctx: HoneyContext) -> list[str]:
        try:
            import importlib.util as _flu
            _spec = _flu.spec_from_file_location("hive2_falsifier", "hive2_falsifier.py")
            _mod = _flu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            block = _mod.get_falsification_report(ctx.mission_id)
            if block:
                return [block, ""]
        except Exception as e:
            log.debug(f"Falsification provider: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 9. OUTLIERS
# ═══════════════════════════════════════════════════════════════════════════════

class OutliersProvider(ContextProvider):
    section_name = "outliers"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== WARTOŚCI ODSTAJĄCE (OUTLIERS) ==="]
        outliers = ctx.honey.get("outliers")

        if outliers:
            for row in outliers:
                val, unit, ctx_text, src_count, _, domains_json, conf = row
                domains = parse_domains_json(domains_json)
                domain_str = ", ".join(domains[:2]) if domains else "?"
                val_str = f"{val:g}" if val is not None else "?"
                unit_str = f" {unit}" if unit else ""
                lines.append(
                    f"[OUTLIER] {val_str}{unit_str} — {ctx_text} "
                    f"(tylko {src_count} źródło, {domain_str})"
                )
        else:
            lines.append("Brak wartości odstających.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CITATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class CitationsProvider(ContextProvider):
    section_name = "citations"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== CYTOWANIA (TOP 30) ==="]
        citations = ctx.honey.get("citations")

        if citations:
            for row in citations[:30]:
                claim, url, domain, title, author, pub_date, conf, cross_val, sup_src = row
                year = pub_date[:4] if pub_date and len(pub_date) >= 4 else "?"
                cv_mark = " ✓" if cross_val else ""
                lines.append(
                    f"• {claim} [{domain}, {year}]{cv_mark} "
                    f"(pewność: {safe_conf(conf)}, wspierające źródła: {sup_src})"
                )
        else:
            lines.append("Brak cytowań.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 11. RESEARCH GAPS (with quality warnings)
# ═══════════════════════════════════════════════════════════════════════════════

class ResearchGapsProvider(ContextProvider):
    section_name = "research_gaps"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = []
        gaps = ctx.honey.get("gaps") or []

        quality_warnings = [row for row in gaps if row[1] == 'quality_warning']
        regular_gaps = [row for row in gaps if row[1] != 'quality_warning']

        if quality_warnings:
            lines.append("⚠️  === OSTRZEŻENIA JAKOŚCI DANYCH ===")
            for row in quality_warnings:
                lines.append(row[0])
            lines.append("")

        lines.append("=== LUKI BADAWCZE ===")
        if regular_gaps:
            for i, row in enumerate(regular_gaps, 1):
                gap_query, gap_type, priority = row
                lines.append(f"{i}. [{gap_type or 'unknown'}, prio={priority}] {gap_query}")
        else:
            lines.append("Brak zidentyfikowanych luk badawczych.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 12. TOP CLAIMS (deduplicated, top 30)
# ═══════════════════════════════════════════════════════════════════════════════

class TopClaimsProvider(ContextProvider):
    section_name = "top_claims"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== TOP CLAIMS (hive_claims — deduplicated, top 30) ==="]
        raw_claims = ctx.honey.get("raw_claims")

        if not raw_claims:
            lines.append("Brak claims.")
            lines.append("")
            return lines

        seen = set()
        added = 0
        for row in raw_claims:
            if len(row) < 5:
                continue
            claim, evidence, src_url, claim_type, conf = row
            dedup_key = (claim or "")[:100].lower().strip()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            domain = extract_domain(src_url)
            evidence_snippet = (evidence or "")[:80]
            lines.append(
                f"[{safe_conf(conf)}] [{claim_type or '?'}] {(claim or '')[:150]}"
                + (f" | evid: {evidence_snippet}" if evidence_snippet else "")
                + (f" | src: {domain}" if domain else "")
            )
            added += 1
            if added >= 30:
                break

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 13. HYPOTHESIS SPACE (QuantumBee)
# ═══════════════════════════════════════════════════════════════════════════════

class HypothesisProvider(ContextProvider):
    section_name = "hypotheses"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== HYPOTHESIS SPACE (QuantumBee / tier≥12) ==="]
        quantum = ctx.honey.get("quantum_hypotheses")

        if not quantum:
            lines.append("Brak danych QuantumBee (tier≥12) dla tej misji.")
            lines.append("")
            return lines

        count = 0
        for row in quantum:
            op_id, op_name, tier, conf, output_json_raw, bee_mission = row
            try:
                oj = json.loads(output_json_raw) if output_json_raw else {}
            except Exception:
                oj = {}

            extracted = self._extract_hypotheses(oj, conf)
            for hyp_text, prob in extracted:
                if not hyp_text:
                    continue
                try:
                    prob_val = f"P={float(prob):.2f}"
                except Exception:
                    prob_val = "P=?"
                lines.append(
                    f"{prob_val} — {str(hyp_text)[:200]} "
                    f"[{op_name}, tier={tier}, mission={bee_mission}]"
                )
                count += 1
                if count >= 15:
                    break
            if count >= 15:
                break

        if count == 0:
            lines.append("Brak wyekstrahowanych hipotez z QuantumBee.")

        lines.append("")
        return lines

    @staticmethod
    def _extract_hypotheses(oj: dict, default_conf) -> list[tuple]:
        """Extract hypothesis tuples from various output_json shapes."""
        extracted = []
        if "hypotheses" in oj and isinstance(oj["hypotheses"], list):
            for h in oj["hypotheses"][:3]:
                if isinstance(h, dict):
                    hyp_text = h.get("hypothesis", h.get("text", ""))
                    prob = h.get("probability", h.get("confidence", default_conf))
                    extracted.append((hyp_text, prob))
                elif isinstance(h, str):
                    extracted.append((h, default_conf))
        elif "resonances" in oj and isinstance(oj["resonances"], list):
            for r_item in oj["resonances"][:2]:
                if isinstance(r_item, dict):
                    r_text = r_item.get("pattern",
                                       r_item.get("description", str(r_item)[:120]))
                    extracted.append((r_text, default_conf))
        elif "key_finding" in oj:
            extracted.append((str(oj["key_finding"])[:200], default_conf))
        return extracted


# ═══════════════════════════════════════════════════════════════════════════════
# 14. CONFIRMED PRIORS (cross-mission)
# ═══════════════════════════════════════════════════════════════════════════════

class PriorsProvider(ContextProvider):
    section_name = "priors"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== CONFIRMED PRIORS (cross-mission) ==="]
        priors = ctx.honey.get("cross_mission_priors")

        if priors:
            for row in priors:
                fact, domain, confidence, times_confirmed, times_contradicted = row
                contra_note = (
                    f" ⚠️ CONTRADICTED {times_contradicted}×"
                    if times_contradicted and times_contradicted > 0 else ""
                )
                lines.append(
                    f"[conf={safe_conf(confidence)}, n={times_confirmed}✓{contra_note}] "
                    f"[{domain}] {fact}"
                )
        else:
            lines.append("Brak potwierdzonych priorów z poprzednich misji.")

        lines.append("")
        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# 15. DEAD HYPOTHESES (Graveyard)
# ═══════════════════════════════════════════════════════════════════════════════

class GraveyardProvider(ContextProvider):
    section_name = "graveyard"

    def render(self, ctx: HoneyContext) -> list[str]:
        lines = ["=== DEAD HYPOTHESES (Graveyard — czego NIE jest prawdą) ==="]
        dead = ctx.honey.get("dead_hypotheses")

        if dead:
            for row in dead:
                hypothesis, topic_domain, failure_reason, conf_at_death = row
                lines.append(
                    f"✗ [{topic_domain or '?'}] {hypothesis} "
                    f"→ OBALONO: {failure_reason} "
                    f"(conf_at_death={safe_conf(conf_at_death)})"
                )
        else:
            lines.append("Brak obalonych hipotez w Graveyard.")

        return lines
