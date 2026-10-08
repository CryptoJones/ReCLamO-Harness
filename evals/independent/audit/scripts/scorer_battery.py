"""Part 2: scorer robustness battery for all 8 active independent-eval tasks.

Usage: python3 -I scorer_battery.py <active_dir> <out_json>
For each task, seeds 0-4 small: run score() on a battery of CORRECT answers in reasonable
formats and WRONG answers. Records every result; flags correct<1 and wrong>=1 (or >=0.5).
"""
import importlib.util, json, os, re, sys

NAMES = ["Cerebex", "GLaDOS", "MasterControl", "Multivac", "Neuromancer", "SELMA", "SHODAN", "TheDixieFlatline"]


def load(src, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(src, name + ".py"))
    g = importlib.util.module_from_spec(spec)
    sys.modules[name] = g
    spec.loader.exec_module(g)
    return g


def money_variants(v, cents=False):
    """Reasonable renderings of a dollar figure v (float)."""
    i = int(round(v))
    out = {}
    if cents or abs(v - i) > 1e-9:
        out["bare"] = f"{v:.2f}"
        out["dollar"] = f"${v:.2f}"
        out["commas_dollar"] = f"${v:,.2f}"
        out["commas"] = f"{v:,.2f}"
        out["usd_suffix"] = f"{v:,.2f} USD"
        out["trailing_period"] = f"${v:,.2f}."
        if abs(v * 10 - round(v * 10)) < 1e-9:
            out["one_decimal"] = f"${v:,.1f}"
    else:
        out["bare"] = f"{i}"
        out["dollar"] = f"${i}"
        out["commas_dollar"] = f"${i:,}"
        out["commas"] = f"{i:,}"
        out["cents"] = f"${i:,}.00"
        out["usd_suffix"] = f"{i:,} USD"
        out["trailing_period"] = f"${i:,}."
    return out


def wrap_scalar(x, label="total"):
    """Wrap a scalar answer string x in common reply formats."""
    return {
        "as_is": x,
        "sentence": f"The answer is {x}.",
        "bold": f"**{x}**",
        "italic": f"*{x}*",
        "bold_in_sentence": f"The {label} is **{x}**.",
        "bullet": f"- {x}",
        "json": json.dumps({label: x}),
        "lead_in_explanation": f"After applying every amendment and reversal, the {label} is {x}.",
        "trailing_explanation": f"{x} (after applying all corrections in the archive)",
        "final_answer_tag": f"Final answer: {x}",
        "code_span": f"`{x}`",
        "uppercase": x.upper(),
        "lowercase": x.lower(),
        "newline_after": f"{x}\n",
        "quoted": f"\"{x}\"",
    }


def other_names(ctx, truth_names, pool=None):
    cands = re.findall(r"\b([A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b", ctx)
    seen = []
    for c in cands:
        if c in truth_names or c in seen:
            continue
        if pool is not None and c not in pool:
            continue
        seen.append(c)
    return seen


# ---------------- per-task batteries ----------------

def b_cerebex(d):
    t = float(d["answer"])
    ok, bad = {}, {}
    for fk, fv in money_variants(t).items():
        for wk, wv in wrap_scalar(fv).items():
            ok[f"{fk}/{wk}"] = wv
    ti = int(round(t))
    ok["explain_count_after"] = f"${ti:,} across the qualifying claims (3 claims)"
    ok["explain_date_after"] = f"${ti:,} (as of the 2024-03-15 amendment)"
    ok["show_work"] = f"Qualifying: 300 + 610 = {ti}. Total: {ti}" if ti else f"No claims qualify. Total: {ti}"
    ok["zero_words"] = "0 - no travel reimbursements qualify" if ti == 0 else f"{ti}"
    ok["none_qualify_word"] = "None qualify, so the total is zero." if ti == 0 else f"{ti}"
    bad["off_by_one"] = str(ti + 1)
    bad["off_by_100"] = f"${ti + 100:,}"
    bad["zero_when_not"] = "0" if ti else "125"
    bad["truth_then_wrong"] = f"I first got {ti} but the final total is {ti + 250}."
    bad["wrong_then_truth_in_text"] = f"The total is {ti + 250} (not {ti})."
    return ok, bad


def glados_text(t, name=None, amt=None, outcome=None):
    name = name or t["certifying_member"]
    amt = t["net_amount"] if amt is None else amt
    outcome = outcome or t["outcome"]
    return name, amt, outcome


def b_glados(d):
    t = d["answer"]; name, amt, out = t["certifying_member"], t["net_amount"], t["outcome"]
    ok, bad = {}, {}
    passed = out == "passed"
    for fk, fv in money_variants(amt).items():
        ok[f"amount_{fk}"] = f"Net authorized amount: {fv}. Certifying member: {name}. The restated authorization {out}."
    ok["json"] = json.dumps({"net_authorized_amount": amt, "certifying_member": name, "passed": passed})
    ok["json_str_outcome"] = json.dumps({"net_amount": amt, "certifying_member": name, "outcome": out})
    ok["bullets_bold"] = f"- **Net authorized amount:** ${amt:,}\n- **Certifying member:** {name}\n- **Passed:** {'Yes' if passed else 'No'}"
    ok["bullets_yes"] = f"- Net authorized amount: ${amt:,}\n- Certifying member: {name}\n- Did it pass? Yes"
    ok["sentence_carried"] = f"The successor's net authorized amount is ${amt:,}; {name} certified it and the motion carried."
    ok["words_million"] = f"${amt/1e6:.2f} million, certified by {name}; it passed."
    ok["uppercase_name"] = f"${amt:,}; {name.upper()}; passed"
    ok["name_no_hyphen"] = f"${amt:,}; {name.replace('-', ' ')}; passed"
    ok["mentions_earlier_failed"] = (f"An earlier attempt failed, but the last restated authorization passed. "
                                     f"Net amount ${amt:,}; certifying member {name}.")
    # wrong
    bad["amount_off"] = f"${amt + 25:,}; {name}; passed"
    others = other_names(d["context"], {name} | set(t.get("name_variants") or []))
    hy = [o for o in others if "-" in o]
    wrong_name = (hy or others or ["Alex Smith"])[0]
    bad["wrong_name"] = f"${amt:,}; {wrong_name}; passed"
    bad["not_approved"] = f"${amt:,}; {name}; it was not approved"
    bad["did_not_pass"] = f"${amt:,}; {name}; it did not pass"
    bad["shotgun_amounts"] = f"Candidates: ${amt - 50000:,}, ${amt:,}, ${amt + 50000:,}; {name}; passed"
    bad["shotgun_names"] = f"${amt:,}; certifying member {wrong_name} (or possibly {name}); passed"
    bad["amount_only"] = f"${amt:,}"
    return ok, bad


def b_mastercontrol(d):
    name, amt = d["answer"]
    ok, bad = {}, {}
    ok["tuple"] = str((name, amt))
    for fk, fv in money_variants(amt).items():
        ok[f"sentence_{fk}"] = f"{name}, with total flagged expenses of {fv}."
    ok["bold"] = f"**{name}** — **${amt:,}**"
    ok["json"] = json.dumps({"employee": name, "total": amt})
    ok["bullets"] = f"- Employee: {name}\n- Total flagged: ${amt:,}"
    ok["lowercase_name"] = f"{name.lower()}, ${amt:,}"
    ok["uppercase_name"] = f"{name.upper()}: ${amt:,}"
    ok["last_first"] = f"{name.split()[-1]}, {name.split()[0]} — ${amt:,}"
    ok["explanation_with_other_numbers"] = f"{name} had 3 flagged reports in Q4 2024 totaling ${amt:,}."
    ok["us_dollars_words"] = f"{name}; {amt:,} dollars"
    emps = ["Lena Carter", "Marcus Boone", "Priya Patel", "Ethan Nguyen", "Sophia Lee"]
    other = [e for e in emps if e != name][0]
    bad["wrong_name"] = f"{other}, ${amt:,}"
    bad["wrong_amount"] = f"{name}, ${amt + 1:,}"
    bad["shotgun_names"] = f"Either {other} or {name}; ${amt:,}"
    bad["shotgun_amounts"] = f"{name}; ${amt - 1000:,} or ${amt:,}"
    bad["name_only"] = name
    return ok, bad


def b_multivac(d):
    t = d["answer"]; rid, st, de = t["req_id"], t["status"], t["description"]
    ok, bad = {}, {}
    ok["str_dict"] = str(t)
    ok["status_colon"] = f"{rid}\nStatus: {st}\nDescription: {de}"
    ok["sentence_is"] = f"The current status of {rid} is {st}, and its full description is: {de}"
    ok["sentence_status_is"] = f"{rid} status is {st}. Description: {de}"
    ok["md_bold_labels"] = f"**{rid}**\n**Status:** {st}\n**Description:** {de}"
    ok["md_bullets_bold"] = f"- **Status**: {st}\n- **Description**: {de}\n(requirement {rid})"
    ok["json"] = json.dumps({"requirement": rid, "status": st, "description": de})
    ok["quoted_status"] = f"{rid} — Status: \"{st}\"; Description: \"{de}\""
    ok["status_dash"] = f"{rid}: Status - {st}; Description - {de}"
    ok["table"] = f"| Requirement | Status | Description |\n|---|---|---|\n| {rid} | {st} | {de} |"
    ok["lower_status"] = f"{rid}\nstatus: {st.lower()}\ndescription: {de}"
    ok["desc_trailing_period"] = f"{rid}\nStatus: {st}\nDescription: {de}."
    ok["desc_collapsed_space"] = f"{rid}\nStatus: {st}\nDescription: {re.sub(' +', ' ', de)}"
    ok["rid_spaced"] = f"Requirement R {rid[1:]}\nStatus: {st}\nDescription: {de}"
    other_st = [s for s in ["Pending", "In Progress", "Completed", "Blocked", "On Hold", "Rejected", "Approved"] if s.lower() != st.lower()][0]
    bad["wrong_status"] = f"{rid}\nStatus: {other_st}\nDescription: {de}"
    bad["partial_desc"] = f"{rid}\nStatus: {st}\nDescription: {de[: max(5, len(de)//2)]}"
    bad["shotgun_status"] = f"{rid}\nStatus: {other_st} (earlier status: {st})\nDescription: {de}"
    bad["desc_plus_extra"] = f"{rid}\nStatus: {st}\nDescription: {de} (Must also support offline mode)"
    return ok, bad


def b_neuromancer(d):
    t = d["answer"]; v = float(t.replace("$", "").replace(",", ""))
    ok, bad = {}, {}
    for fk, fv in money_variants(v, cents=True).items():
        for wk, wv in wrap_scalar(fv).items():
            ok[f"{fk}/{wk}"] = wv
    ok["explain_after"] = f"${v:,.2f} reimbursed across 4 March travel claims"
    bad["off_by_cent"] = f"${v + 0.01:.2f}"
    bad["rounded"] = f"${round(v):,}"
    bad["off_by_one"] = f"${v + 1:.2f}"
    bad["shotgun"] = f"Either ${v - 100:.2f} or ${v:.2f}"
    bad["truth_negated"] = f"Not ${v:.2f}; it is ${v + 200:.2f}"
    return ok, bad


def b_selma(d):
    t = d["answer"]; ok, bad = {}, {}
    if t == "Unassigned":
        x = "Unassigned"
        for wk, wv in wrap_scalar(x, "owner").items():
            ok[f"{wk}"] = wv
        ok["sentence_currently"] = "The AI Ethics Review is currently unassigned."
        ok["no_one"] = "No one is currently assigned (Unassigned)."
        ok["dash_explain"] = "Unassigned — the last owner was removed and nobody replaced them."
        ok["final_owner_unassigned"] = "Final owner: Unassigned"
        ok["none"] = "None"
        others = other_names(d["context"], set())
        bad["a_name"] = others[0] if others else "Alex Smith"
        bad["assigned"] = "Assigned"
        bad["not_unassigned"] = "It is not unassigned; the owner is " + (others[0] if others else "Alex Smith")
    else:
        for wk, wv in wrap_scalar(t, "owner").items():
            ok[f"{wk}"] = wv
        ok["final_owner_label"] = f"Final owner: {t}"
        ok["with_dept"] = f"{t} (Engineering)"
        ok["possessive"] = f"It is {t}'s responsibility."
        ok["md_bold_in_sentence"] = f"The final owner is **{t}**."
        ok["last_first"] = f"{t.split()[-1]}, {t.split()[0]}"
        ok["quoted_in_sentence"] = f"The final owner is \"{t}\"."
        ok["name_then_comma"] = f"{t}, who took over after the last reassignment."
        others = other_names(d["context"], {t})
        o = others[0] if others else "Alex Smith"
        bad["other_name"] = o
        bad["first_name_only"] = t.split()[0]
        bad["shotgun_two_names"] = f"Ownership moved from {t} to {o}; the final owner is {o}."
        bad["unassigned"] = "Unassigned"
    return ok, bad


def b_shodan(d):
    t = d["answer"]; ok, bad = {}, {}
    offs = list(t)
    ok["json"] = json.dumps(t)
    ok["json_pretty"] = json.dumps(t, indent=2)
    ok["py_dict"] = str(t)
    ok["colon_lines"] = "\n".join(f"{o}: {t[o]}" for o in offs)
    ok["bullets_bold"] = "\n".join(f"- **{o}**: {t[o]}" for o in offs)
    ok["md_table"] = "| Office | Credits |\n|---|---|\n" + "\n".join(f"| {o} | {t[o]} |" for o in offs)
    ok["credits_suffix"] = "\n".join(f"{o}: {t[o]} credits" for o in offs)
    ok["office_word"] = "\n".join(f"{o} office: {t[o]}" for o in offs)
    ok["Office_label_json"] = json.dumps({f"{o} Office": t[o] for o in offs})
    ok["prose_earned"] = "; ".join(f"{o} earned {t[o]}" for o in offs) + "."
    ok["intro_list"] = ("Totals for Alderwick, Brindleford, Cairnstead, Dunmere, Elmbridge, Fenhurst and Gorsehaven:\n"
                        + "\n".join(f"{o}: {t[o]}" for o in offs))
    ok["fenced_json"] = "```json\n" + json.dumps(t, indent=2) + "\n```"
    ok["equals"] = ", ".join(f"{o} = {t[o]}" for o in offs)
    ok["with_note_after"] = json.dumps(t) + "\nNote: offices with no qualifying shipments are 0."
    ok["em_dash"] = "\n".join(f"{o} — {t[o]}" for o in offs)
    ok["zero_word_none"] = "\n".join(f"{o}: {t[o] if t[o] else '0 (none)'}" for o in offs)
    ok["paren_unit"] = "\n".join(f"{o}: {t[o]} (credits)" for o in offs)
    nz = [o for o in offs if t[o]] or offs[:1]
    w = dict(t); w[nz[0]] = t[nz[0]] + 1
    bad["off_by_one"] = json.dumps(w)
    m = dict(t); m.pop(offs[-1]); bad["missing_office"] = json.dumps(m)
    z = {o: 0 for o in offs}; bad["all_zero"] = json.dumps(z)
    sw = dict(t); sw[nz[0]], sw[offs[0] if offs[0] != nz[0] else offs[1]] = 0, t[nz[0]]
    bad["swapped"] = json.dumps(sw)
    return ok, bad


def b_dixie(d):
    t = d["answer"]; ok, bad = {}, {}
    for wk, wv in wrap_scalar(t, "location").items():
        ok[wk] = wv
    ok["long_sentence"] = f"The final physical location of the asset originally known as 'The Genesis Drive' is {t}."
    ok["medium_sentence"] = f"The asset's final physical location is {t}."
    if t.startswith("The "):
        ok["no_article"] = t[4:]
    locs = [f"Room {i}" for i in range(101, 150)] + ["The Vault", "Datacenter Alpha", "Datacenter Beta", "Offsite Storage",
                                                     "Basement Level 1", "Executive Suite", "The Annex", "Server Room C"]
    others = [l for l in locs if l != t and l in d["context"]]
    bad["other_location"] = others[0] if others else "The Annex"
    bad["shotgun_two"] = f"{t} or {others[1] if len(others) > 1 else 'The Annex'}"
    bad["previous_location_too"] = f"It moved from {others[0] if others else 'Room 101'} to {t}"
    if t.startswith("Room "):
        n = int(t.split()[1])
        bad["off_by_one_room"] = f"Room {n + 1 if n < 149 else n - 1}"
        bad["number_only"] = str(n)
    return ok, bad


BATT = {"Cerebex": b_cerebex, "GLaDOS": b_glados, "MasterControl": b_mastercontrol, "Multivac": b_multivac,
        "Neuromancer": b_neuromancer, "SELMA": b_selma, "SHODAN": b_shodan, "TheDixieFlatline": b_dixie}


def main():
    src, out = sys.argv[1], sys.argv[2]
    results = {}
    flags = []
    for name in NAMES:
        g = load(src, name)
        results[name] = {}
        for seed in range(5):
            d = g.generate(seed, "small")
            ok, bad = BATT[name](d)
            cell = {"truth": repr(d["answer"]), "correct": {}, "wrong": {}}
            for k, s in ok.items():
                sc = g.score(s, d["answer"])
                cell["correct"][k] = {"answer": s, "score": sc}
                if sc < 1:
                    flags.append({"task": name, "seed": seed, "kind": "correct<1", "variant": k, "answer": s, "score": sc,
                                  "truth": repr(d["answer"])})
            for k, s in bad.items():
                sc = g.score(s, d["answer"])
                cell["wrong"][k] = {"answer": s, "score": sc}
                if sc >= 0.5:
                    flags.append({"task": name, "seed": seed, "kind": "wrong>=0.5" if sc < 1 else "wrong>=1",
                                  "variant": k, "answer": s, "score": sc, "truth": repr(d["answer"])})
            results[name][seed] = cell
    json.dump({"results": results, "flags": flags}, open(out, "w"), indent=1)
    # summary
    from collections import Counter, defaultdict
    by = defaultdict(lambda: defaultdict(list))
    for f in flags:
        by[(f["task"], f["kind"])][f["variant"]].append((f["seed"], f["score"]))
    for (task, kind), vs in sorted(by.items()):
        print(f"== {task} {kind}")
        for v, ss in vs.items():
            print(f"   {v}: seeds/scores {ss}")
    tot = sum(len(c["correct"]) + len(c["wrong"]) for t in results.values() for c in t.values())
    print("total probes", tot, "flags", len(flags))


if __name__ == "__main__":
    main()
