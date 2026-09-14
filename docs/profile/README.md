# Jack Riddle

## Featured project: [tennis-lab](https://github.com/riddlejack/tennis-lab)

**How far can public tennis statistics take a pre-match forecast?** tennis-lab builds a
chronological model ladder to find out: Elo first, then a boosted model over results and
match context, dynamic serve/return states, and richer lower-tour histories.

On the same priced retrospective matches, every added statistics rung improved log loss.
For ATP, the ladder moved from 0.6237 for Elo to 0.5984 for the full-tier model, while
normalised Pinnacle recorded 0.5873. WTA showed the same direction: 0.6265 for Elo,
0.6153 for the full model, and 0.5953 for Pinnacle.

The engineering story matters too. Separate LLM roles built, challenged, and independently
reconstructed the work. Reviews uncovered invented match dates, a future-learned
constant, scoring before a report barrier, and tests that stayed green when defects were
planted. Those failures remain visible and now drive concrete contracts and regression
tests in one reproducible Python trunk.

The project is retrospective research. Its external-benchmark design exists, but an
accepted matched comparison, the real-history snapshot, and a scored prospective record
remain open.
