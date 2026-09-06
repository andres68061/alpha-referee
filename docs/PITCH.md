# Why this, for this reader

Mark Horvath's MSCI mandate, in his own words, is an *"agentic implementation and
human-in-the-loop validation platform for sourcing quantitative investment
strategies from published equity research."*

Two halves. The first half — an agent that reads papers and emits candidate
signals — is now cheap, and getting cheaper every quarter. The second half is
the constraint: the human in "human-in-the-loop" does not scale, and the
platform's throughput is bounded by how fast a researcher can decide whether a
proposed signal is real.

`alpha-referee` is an attempt at the second half. It is a mechanical, ordered,
pre-registered adjudication of a candidate signal, ending in a decay waterfall
rather than a verdict, with a trial ledger that makes the multiple-testing
correction auditable instead of self-reported.

Three things about it are aimed squarely at that reader:

**The trial ledger.** He ran a book at 1.68 live Sharpe for seven years. He does
not need to be told that backtests overfit. What is new is the mechanism: `N` is
read off a hash-chained record written before each run, so it cannot be
understated. That is a systems answer to a statistics problem, which is the
register he works in.

**Sector- and factor-neutral by default.** His MSCI bullet says he *"aligned
cross-sectional signals to isolate the performance of common risk factors from
investment signals."* The orthogonalization gate is that step, made compulsory
rather than optional, and reported as a give-up rather than buried.

**Data integrity as a first-class gate.** This is the part nobody else brings.
Validating reported financial data against source documents, flagging anomalous
movements, and filtering by materiality is a day job, not a hobby — and it is
exactly the failure mode an agentic pipeline is blindest to. An agent will
happily discover alpha in a missed corporate action.

The honest framing for a first message is not "hire me." It is: *here is a
replication of a published text signal with the corrections applied in a fixed
order, here is where it died, and here is the harness — does the give-up
waterfall match what you see internally?* That is a question a researcher
answers. "Are you hiring" is a question a researcher forwards to HR.
