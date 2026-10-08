"""Solve a SHODAN context from the TEXT alone (no generator import).

Usage: python3 -I part1_SHODAN_solve.py <ctx.txt>
Every paragraph must match a known phrase pattern; unknown paragraphs are printed
so a human can extend the phrase tables (no silent guessing).
"""
import re, sys, json

text = open(sys.argv[1]).read()
paras = [p.strip().replace("\n", " ") for p in text.split("\n\n") if p.strip()]
Q = "[“\"]([^”\"]+)[”\"]"

PASS = ["passed", "met its limit", "met its contractual limit", "final verdict is satisfactory", "success stands",
        "No failure remained"]
FAIL = ["failed", "did not meet its limit", "did not pass", "signed verdict is unsatisfactory", "failure stands",
        "failed its contractual limit"]
QUAL = {
    "One successful trial suffices, and two successes are also accepted.": "atleast",
    "Neither trial may fail": "both",
    "At least one of moisture and vibration must succeed.": "atleast",
    "The results must disagree: one success and one failure.": "exactly",
    "Exactly one of moisture and vibration must succeed.": "exactly",
    "Reject only the combination in which neither trial passes.": "atleast",
    "A success in only one trial is insufficient; each must pass.": "both",
    "Two successes are no more acceptable than two failures; one trial must pass and the other fail.": "exactly",
    "Both moisture and vibration must succeed.": "both",
}
SEAL = {
    "The dispatched crate's seal was broken; the intact seal belonged to a training tote.": False,
    "The inspector withdrew the intact-seal claim about the shipment. Its own seal had been breached.": False,
    "The former had an intact seal; the latter did not.": False,
    "The former had a torn seal; the latter did not.": True,
    "The dispatched crate's seal remained intact; the broken strap belonged to a training tote.": True,
    "The inspector withdrew the damage claim about the shipment's seal. That seal was unbroken.": True,
}
WAIVER_SIGNED = {"The packaging waiver was signed, rather than merely requested.": True,
                 "The claim that nobody signed the packaging waiver is false; the signed copy is attached.": True,
                 "No signed packaging waiver exists for this shipment.": False,
                 "The supposed signed packaging waiver was only an unsigned draft.": False,
                 "A packaging waiver was requested but never signed.": False,
                 "A signed packaging waiver is in the booking envelope.": True}
CUSTODY = {
    "The former stayed with the consignee at closing; the latter returned to the depot.": True,
    "The actual shipment remained with the consignee at closing.": True,
    "At closing the consignee still held the shipment.": True,
    "The consignee retained it through closing; no later return occurred.": True,
    "At closing it was at the depot": False,
    "The shipment was collected from the consignee before closing.": False,
    "The former returned to the depot before closing; the latter stayed with the consignee.": False,
    "The actual shipment was back at the depot at closing.": False,
}


def verdict(s):
    # order-sensitive: check FAIL-ish negations first
    for f in ["did not meet its limit", "did not pass", "unsatisfactory", "failure stands", "failed its contractual"]:
        if f in s:
            return False
    if "allegation that" in s and "failed was withdrawn" in s:
        return True
    for p in PASS:
        if p in s:
            return True
    if "failed" in s:
        return False
    raise ValueError(s)


radio, prov_mgr, prov_office, mgr, office, agr0, agr, ship, lab, cust, acct = {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}
unknown = []
for p in paras:
    m = re.match(r"Directory card for (.+?): radio name " + Q, p)
    if m: radio[m[2]] = m[1]; continue
    m = re.match(r"Calls to " + Q + r" reach (.+?)\.", p)
    if m: radio[m[1]] = m[2]; continue
    m = re.match(r"Office register: (.+?)'s provisional accounting office is (\w+)\.", p)
    if m: prov_office[m[1]] = m[2]; continue
    m = re.match(r"Closing personnel review for (.+?): the candidates were (.+?) and (.+?)\. The (former|latter) was not appointed; the (former|latter) is the line manager", p)
    if m: mgr[m[1]] = m[2] if m[5] == "former" else m[3]; continue
    m = re.match(r"Signed personnel correction — (.+?)\. For the May closing, the line manager is (.+?), not", p)
    if m: mgr[m[1]] = m[2]; continue
    m = re.match(r"The closing registration for (.+?) considered (\w+) and (\w+)\. Only the (former|latter) was approved", p)
    if m: office[m[1]] = m[2] if m[4] == "former" else m[3]; continue
    m = re.match(r"Signed office correction for (.+?): use (\w+) for May closing attribution", p)
    if m: office[m[1]] = m[2]; continue
    m = re.match(r"(Original|Signed closing amendment to) (\w+)", p)
    if m and ("agreement" in p or "amendment" in p):
        name = re.match(r"Original (\w+) agreement", p)[1] if p.startswith("Original") else m[2]
        q = [v for k, v in QUAL.items() if k in p]
        rate = int(re.search(r"(?:rate is|rate becomes) (\d+) credits", p)[1])
        allow = int(re.search(r"allowance (?:is|becomes) (\d+) units", p)[1])
        w = "may excuse" in p
        assert len(q) == 1 and ("cannot excuse" in p) != w, p
        (agr0 if p.startswith("Original") else agr)[name] = dict(q=q[0], rate=rate, allow=allow, waiver=w)
        continue
    m = re.match(r"Booking letter — (FR-\d+), known to the carrier as " + Q, p)
    if m:
        a = re.search(r"Sales compared (\w+) with (\w+); the (former|latter) was executed", p)
        if a: ag = a[1] if a[3] == "former" else a[2]
        else: ag = re.search(r"booked under (\w+)\.", p)[1]
        ws = [v for k, v in WAIVER_SIGNED.items() if k in p]
        assert len(ws) == 1, p
        ship[m[1]] = dict(nick=m[2], agr=ag, waiver=ws[0], open=re.search(r"opening contact was " + Q, p)[1]); continue
    m = re.match(r"Signed replacement laboratory report — (FR-\d+)\. The (moisture|vibration) and (moisture|vibration) trials were reconsidered in that order\. The former (.+?); the latter (.+?)\.", p)
    if m:
        r = {m[2]: verdict(m[4]), m[3]: verdict(m[5])}
        s = [v for k, v in SEAL.items() if k in p]
        assert len(s) == 1, p
        lab[m[1]] = dict(M=r["moisture"], V=r["vibration"], seal=s[0]); continue
    m = re.match(r"Signed final carrier audit for " + Q, p)
    if m:
        c = [v for k, v in CUSTODY.items() if k in p]
        assert len(c) == 1, p
        cust[m[1]] = c[0]; continue
    m = re.match(r"Final accounts reconciliation for " + Q, p)
    if m:
        a = re.search(r"signed shipped quantity is (\d+) units, of which (\d+) are damaged", p)
        if a: n, d = int(a[1]), int(a[2])
        else:
            a = re.search(r"damaged portion is (\d+) units within a total shipped quantity of (\d+)", p); d, n = int(a[1]), int(a[2])
        c = re.search(Q + r" and " + Q + r" were proposed as responsible contact and reserve respectively\. The (former|latter) accepted responsibility", p)
        if c: who = c[1] if c[3] == "former" else c[2]
        else:
            c = re.search(Q + r" was considered before " + Q + r"\. The (first|second) was declined; the (first|second) is the responsible contact", p)
            who = c[1] if c[4] == "first" else c[2]
        acct[m[1]] = dict(n=n, d=d, contact=who); continue
    if p.startswith(("Preliminary laboratory note", "Carrier message concerning", "Freight cooperative", "The closing date",
                     "Closing instructions", "* ", "The requested result", "Personnel desk", "Commercial desk",
                     "Booking correspondence", "Laboratory desk", "Carrier desk", "Accounts desk", "Personnel and commercial")):
        continue
    unknown.append(p)

OFFICES = ["Alderwick", "Brindleford", "Cairnstead", "Dunmere", "Elmbridge", "Fenhurst", "Gorsehaven"]
tot = {o: 0 for o in OFFICES}
rows = []
for fr, s in ship.items():
    a = agr.get(s["agr"], agr0[s["agr"]])
    L = lab[fr]; ret = cust[s["nick"]]; ac = acct[s["nick"]]
    k = L["M"] + L["V"]
    qual = {"both": k == 2, "atleast": k >= 1, "exactly": k == 1}[a["q"]]
    pack = L["seal"] or (s["waiver"] and a["waiver"])
    person = radio[ac["contact"]]; m_ = mgr[person]; off = office[m_]
    units = max(ac["n"] - ac["d"] - a["allow"], 0)
    credit = units * a["rate"] if (ret and qual and pack) else 0
    tot[off] += credit
    rows.append((fr, s["nick"], s["agr"], a["q"], L["M"], L["V"], L["seal"], s["waiver"], a["waiver"], ret, qual, pack,
                 ac["n"], ac["d"], a["allow"], a["rate"], ac["contact"], person, m_, off, credit))
for r in rows: print(r)
print("UNKNOWN:", unknown)
print("missing agreement amendments:", set(agr0) - set(agr))
print(json.dumps(tot))
