# LinkedIn draft — impact-audited

> Status: DRAFT for review. Not posted. Run the four-flag pre-screen before posting.

---

Your code-graph tool might be lying to you — quietly, and with confidence.

"Blast radius" tools and codebase knowledge-graph MCPs answer *"what breaks if I
change this function?"* for AI agents and humans alike. They're fast and they
read authoritative. But they share a failure mode nobody warns you about: if the
indexer trips on one large file and drops it, every dependency edge through that
file silently vanishes — and the tool keeps answering as if the file never
existed. You get "low risk, one caller" for a function used across your core.

So I built a small guard for it: **impact-audited**.

The idea is boring on purpose. Cross-check the graph tool's answer against the
cheapest possible ground truth — grep for the direct call sites — and treat the
*disagreement* as the signal. If grep finds a caller the graph missed, that edge
isn't in the index, and you're told loudly instead of trusting a silent gap.
A deterministic floor + an opaque richer layer + an independent confirmation net.

I ran it over two widely-used public Python libraries to see if the problem was
real. It was:

• On `requests`, a popular graph tool (v1.6.3) silently dropped models.py,
  sessions.py and utils.py — the core of the library — and its impact analysis
  was therefore incomplete for 70% of top-level symbols. `to_key_val_list` came
  back "LOW risk, one caller." Two of the library's most central modules call it.

• Fairness check: a different knowledge-graph tool indexed every file with no
  gap. So this isn't "all these tools are broken" — it's "some drop files
  silently and you usually can't tell which." Which is exactly why a cheap,
  independent check earns its keep.

The audit stays quiet when there's no gap (it's calibrated, not a smoke alarm),
costs a few hundred tokens, and works with any tool that prints file paths.
Single file, MIT, standard-library only.

Repo + reproducible benchmark: github.com/klmtseng/impact-audited

Verification you didn't ask for beats confidence you can't check. Curious whether
others have hit the same silent-index-drop failure with their tooling.

#AI #DeveloperTools #CodeIntelligence #Evaluation #SoftwareEngineering
