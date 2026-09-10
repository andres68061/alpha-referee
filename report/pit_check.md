# Gate 0 — point-in-time audit

Sample: 2474 10-K filings, 185 firms, 2012-01–2025-12.

| alignment   |    n |   n_lookahead |   pct_lookahead |   median_gap_days |   min_gap_days | passed   |
|:------------|-----:|--------------:|----------------:|------------------:|---------------:|:---------|
| period_end  | 2474 |          2474 |             100 |         -50.0173  |     -389.01    | False    |
| acceptance  | 2474 |             0 |               0 |           1.98736 |        1.00028 | True     |

The naive alignment is what a careless replication does: it dates the
signal at the fiscal period end, because that is the date the financial
data describes. The document itself did not exist until EDGAR accepted
it, a median of 50 calendar days later.
