# evals/regression/

One JSON file per confirmed exploit: `VR-####.json`. Schema mirrors
`agentforge.regression.case_schema.RegressionCase`. Files are emitted by
`agentforge.documentation.regression_curator.RegressionCurator` (which refuses
to write when `what_bug_this_catches` is empty).
